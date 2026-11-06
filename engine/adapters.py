"""Persisted polyglot dependency updates with native resolved-version checks.

Unsupported/ambiguous manifest forms fail before mutation. Every command runs
inside the isolated checkout, never the customer's original working tree.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET


def checked(command, cwd="."):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=180)
    if result.returncode:
        raise ValueError(f"Native dependency inspection failed: {command[0]}")
    return result.stdout


def project_directory(vuln):
    path = Path(vuln.get("working_dir", ".")).resolve()
    if not path.is_relative_to(Path.cwd().resolve()) or not path.is_dir():
        raise ValueError("Project directory must remain inside checkout")
    return path


def validate_arguments(package, target):
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./:@+-]*", package):
        raise ValueError("Unsafe package identifier")
    if not re.fullmatch(r"v?[0-9]+(?:\.[0-9A-Za-z]+)+(?:[-+][A-Za-z0-9.-]+)?", target):
        raise ValueError("Target must be an exact release version")


def tracked(path):
    if path.is_symlink() or not path.resolve().is_relative_to(Path.cwd().resolve()):
        raise ValueError("Manifest path escapes checkout")
    checked(["git", "ls-files", "--error-unmatch", "--", str(path.relative_to(Path.cwd()))])


def prepare_baseline(run_directory, ecosystem=None):
    """Prepare dependencies outside the source checkout where possible."""
    root = Path.cwd()
    if (root / "package.json").exists() and ecosystem in (None, "npm"):
        if not (root / "package-lock.json").exists():
            raise RuntimeError("A committed npm lockfile is required")
        return "npm ci --ignore-scripts --no-audit --no-fund"
    if ((root / "requirements.txt").exists() or (root / "pyproject.toml").exists()) and ecosystem in (None, "pypi", "python"):
        environment = Path(run_directory) / "python-env"
        checked([sys.executable, "-m", "venv", str(environment)])
        binaries = environment / ("Scripts" if os.name == "nt" else "bin")
        os.environ["PATH"] = str(binaries) + os.pathsep + os.environ.get("PATH", "")
        os.environ["VIRTUAL_ENV"] = str(environment)
        os.environ["UV_PROJECT_ENVIRONMENT"] = str(environment)
        if (root / "requirements.txt").exists():
            return "python -m pip install --disable-pip-version-check -r requirements.txt"
        if (root / "poetry.lock").exists():
            return "poetry install --no-interaction"
        if not (root / "uv.lock").exists():
            raise RuntimeError("PEP621 project execution requires a committed uv.lock")
        return "uv sync --locked"
    if (root / "go.mod").exists() and ecosystem in (None, "go"):
        return "go mod download"
    if (root / "Cargo.toml").exists() and ecosystem in (None, "crates.io", "rust", "cargo"):
        return "cargo fetch --locked"
    if (root / "pom.xml").exists() and ecosystem in (None, "maven", "java"):
        return "mvn -B -ntp dependency:resolve"
    if ((root / "build.gradle").exists() or (root / "build.gradle.kts").exists()) and ecosystem in (None, "maven", "java"):
        return None  # The baseline test command resolves Gradle dependencies.
    if list(root.glob("*.csproj")) and ecosystem in (None, "nuget", "dotnet"):
        return "dotnet restore"
    return None


def update(vuln):
    package, target = vuln["package"], vuln["target_version"]
    validate_arguments(package, target)
    root = project_directory(vuln)
    if root != Path.cwd().resolve():
        raise ValueError("Select the target project with --project before non-npm remediation")
    ecosystem = vuln.get("ecosystem", "").lower()
    if ecosystem in ("pypi", "python"):
        requirement = root / "requirements.txt"
        if requirement.exists():
            tracked(requirement)
            source = requirement.read_text(encoding="utf-8")
            pattern = re.compile(r"(?im)^([ \t]*)" + re.escape(package) + r"(\[[^\]\n]+\])?(?:[ \t]*(?:===|==|~=|>=|<=|>|<|!=)[^;#\r\n]*?)?([ \t]*(?:;[^#\r\n]+)?[ \t]*(?:#[^\r\n]*)?)$")
            matches = list(pattern.finditer(source))
            if len(matches) != 1:
                raise ValueError("Python dependency must have one direct requirements declaration")
            source = pattern.sub(lambda m: m.group(1) + package + (m.group(2) or "") + "==" + target + m.group(3), source)
            requirement.write_text(source, encoding="utf-8")
            return "python -m pip install --disable-pip-version-check -r requirements.txt && python -m pip check", str(root)
        manifest = root / "pyproject.toml"
        tracked(manifest)
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        poetry = data.get("tool", {}).get("poetry", {})
        if (root / "poetry.lock").exists():
            groups = [("tool.poetry.dependencies", poetry.get("dependencies", {}))]
            groups += [("tool.poetry.group." + group + ".dependencies", group_data.get("dependencies", {}))
                       for group, group_data in poetry.get("group", {}).items()]
            selected = [(section, entries[package]) for section, entries in groups if package in entries]
            if len(selected) != 1:
                raise ValueError("Poetry requires one direct dependency declaration")
            section, declaration = selected[0]
            source = manifest.read_text(encoding="utf-8")
            block = re.search(r"(?ms)^\[" + re.escape(section) + r"\]\s*\n(.*?)(?=^\[|\Z)", source)
            if not block:
                raise ValueError("Unsupported Poetry dependency table")
            body = block.group(1)
            if isinstance(declaration, str):
                pattern = re.compile(r"(?m)^(\s*" + re.escape(package) + r"\s*=\s*)[\"'][^\"']+[\"']")
            elif isinstance(declaration, dict) and "version" in declaration and not any(key in declaration for key in ("path", "git", "url")):
                pattern = re.compile(r"(?m)^(\s*" + re.escape(package) + r"\s*=\s*\{[^\n]*?\bversion\s*=\s*)[\"'][^\"']+[\"']")
            else:
                raise ValueError("Poetry source/conditional dependency requires manual review")
            if len(pattern.findall(body)) != 1:
                raise ValueError("Ambiguous Poetry declaration")
            body = pattern.sub(lambda match: match.group(1) + '"' + target + '"', body)
            source = source[:block.start(1)] + body + source[block.end(1):]
            tomllib.loads(source)
            manifest.write_text(source, encoding="utf-8")
            return "poetry lock && poetry install --no-interaction", str(root)
        dependencies = data.get("project", {}).get("dependencies", [])
        normalize = lambda value: re.sub(r"[-_.]+", "-", value).lower()
        matches = [dep for dep in dependencies if normalize(re.split(r"[<>=!~\[ ;]", dep, 1)[0]) == normalize(package)]
        if len(matches) != 1:
            raise ValueError("Python pyproject requires one PEP621 direct dependency; Poetry-specific tables require manual migration")
        from packaging.requirements import Requirement
        declaration = Requirement(matches[0])
        if declaration.extras or declaration.marker or declaration.url:
            raise ValueError("PEP621 extras, markers, and URL dependencies require manual review")
        return f"uv add --no-sync {package}=={target} && uv sync --locked", str(root)
    if ecosystem == "go":
        if not target.startswith("v"):
            target = "v" + target
            vuln["target_version"] = target
        tracked(root / "go.mod")
        if not re.search(r"(?m)^\s*(?:require\s+)?" + re.escape(package) + r"\s+v?\d", (root / "go.mod").read_text()):
            raise ValueError("Module must already be declared in go.mod")
        return f"go get {package}@{target} && go mod tidy", str(root)
    if ecosystem in ("crates.io", "cargo", "rust"):
        manifest = root / "Cargo.toml"
        tracked(manifest)
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        matches = [section for section in ("dependencies", "dev-dependencies", "build-dependencies") if package in data.get(section, {})]
        if len(matches) != 1:
            raise ValueError("Cargo dependency must have one direct declaration")
        section = matches[0]
        source = manifest.read_text(encoding="utf-8")
        block = re.compile(r"(?ms)(^\[" + re.escape(section) + r"\]\s*\n)(.*?)(?=^\[|\Z)")
        found = block.search(source)
        if not found:
            raise ValueError("Cargo dependency table form is unsupported")
        body = found.group(2)
        simple = re.compile(r"(?m)^(\s*" + re.escape(package) + r"\s*=\s*)[\"'][^\"']+[\"'](\s*(?:#.*)?)$")
        if len(simple.findall(body)) == 1:
            body = simple.sub(lambda m: m.group(1) + '"=' + target + '"' + m.group(2), body)
        else:
            inline = re.compile(r"(?m)^(\s*" + re.escape(package) + r"\s*=\s*\{[^\n]*?\bversion\s*=\s*)[\"'][^\"']+[\"']([^\n]*\})")
            if len(inline.findall(body)) != 1:
                raise ValueError("Cargo workspace/path/renamed dependency requires explicit supported declaration")
            body = inline.sub(lambda m: m.group(1) + '"=' + target + '"' + m.group(2), body)
        source = source[:found.start(2)] + body + source[found.end(2):]
        tomllib.loads(source)
        manifest.write_text(source, encoding="utf-8")
        return f"cargo update -p {package} --precise {target} && cargo fetch --locked", str(root)
    if ecosystem in ("maven", "java"):
        pom = root / "pom.xml"
        if pom.exists():
            tracked(pom)
            group, artifact = package.split(":", 1)
            tree = ET.parse(pom)
            document = tree.getroot()
            namespace = document.tag.split("}")[0][1:] if "}" in document.tag else ""
            tag = lambda name: f"{{{namespace}}}{name}" if namespace else name
            if namespace:
                ET.register_namespace("", namespace)
            matches = [dependency for dependency in document.iter(tag("dependency"))
                       if dependency.findtext(tag("groupId")) == group and dependency.findtext(tag("artifactId")) == artifact]
            if len(matches) != 1 or matches[0].find(tag("version")) is None:
                raise ValueError("Maven requires one explicitly versioned dependency")
            element = matches[0].find(tag("version"))
            if element.text and element.text.startswith("${"):
                property_name = element.text[2:-1]
                if pom.read_text().count(element.text) != 1:
                    raise ValueError("Shared Maven version property is ambiguous")
                element = document.find(f"{tag('properties')}/{tag(property_name)}")
                if element is None:
                    raise ValueError("Maven version property not defined in this POM")
            element.text = target
            tree.write(pom, encoding="utf-8", xml_declaration=True)
            return "mvn -B -ntp dependency:resolve", str(root)
        build = root / "build.gradle"
        if not build.exists():
            build = root / "build.gradle.kts"
        tracked(build)
        source = build.read_text(encoding="utf-8")
        pattern = re.compile(r"([\"'])" + re.escape(package) + r":[^\"'\n]+\1")
        if len(pattern.findall(source)) != 1:
            raise ValueError("Gradle requires one literal group:artifact:version declaration")
        source = pattern.sub(lambda m: m.group(1) + package + ":" + target + m.group(1), source)
        if "dependencyLocking" not in source:
            source += "\ndependencyLocking { lockAllConfigurations() }\n"
        build.write_text(source, encoding="utf-8")
        command = "gradlew.bat" if os.name == "nt" and (root / "gradlew.bat").exists() else "./gradlew" if (root / "gradlew").exists() else "gradle"
        return command + " dependencies --write-locks --no-daemon", str(root)
    if ecosystem in ("nuget", "dotnet"):
        projects = list(root.glob("*.csproj"))
        if len(projects) != 1:
            raise ValueError("Select a directory with exactly one .csproj")
        tracked(projects[0])
        document = ET.parse(projects[0]).getroot()
        references = [node for node in document.iter("PackageReference") if node.attrib.get("Include", "").lower() == package.lower()]
        if len(references) != 1:
            raise ValueError("NuGet package must be a direct PackageReference")
        return f"dotnet add package {package} --version {target} && dotnet restore --use-lock-file", str(root)
    raise ValueError("No persisted adapter for ecosystem " + ecosystem)


def validate_target(vuln):
    package, target = vuln["package"], vuln["target_version"]
    root = project_directory(vuln)
    ecosystem = vuln.get("ecosystem", "").lower()
    if ecosystem in ("pypi", "python"):
        output = checked(["python", "-c", "import importlib.metadata,sys; print(importlib.metadata.version(sys.argv[1]))", package], root)
        if output.strip() != target:
            raise ValueError("Installed Python version differs from target")
        if (root / "requirements.txt").exists() and not re.search(r"(?mi)^" + re.escape(package) + r"(?:\[[^\]\n]+\])?==" + re.escape(target) + r"(?:\s|;|#|$)", (root / "requirements.txt").read_text()):
            raise ValueError("Python pin was not persisted")
        if (root / "uv.lock").exists():
            lock = tomllib.loads((root / "uv.lock").read_text())
            if not any(item.get("name") == package and item.get("version") == target for item in lock.get("package", [])):
                raise ValueError("uv lockfile target mismatch")
        if (root / "poetry.lock").exists():
            lock = tomllib.loads((root / "poetry.lock").read_text())
            if not any(item.get("name") == package and item.get("version") == target for item in lock.get("package", [])):
                raise ValueError("Poetry lockfile target mismatch")
    elif ecosystem == "go":
        resolved = json.loads(checked(["go", "list", "-m", "-json", package], root))
        if resolved.get("Version") != target or resolved.get("Replace"):
            raise ValueError("Resolved Go module does not match target")
        if not re.search(r"(?m)^" + re.escape(package) + " " + re.escape(target) + r"(?:/go.mod)? h1:", (root / "go.sum").read_text()):
            raise ValueError("Go checksum missing")
    elif ecosystem in ("crates.io", "cargo", "rust"):
        lock = tomllib.loads((root / "Cargo.lock").read_text())
        selected = [item for item in lock.get("package", []) if item.get("name") == package]
        if not selected or any(item.get("version") != target or not item.get("checksum") for item in selected):
            raise ValueError("Cargo lockfile has missing/different target versions")
        resolved = json.loads(checked(["cargo", "metadata", "--locked", "--format-version", "1"], root))
        if not any(item.get("name") == package and item.get("version") == target for item in resolved.get("packages", [])):
            raise ValueError("Cargo resolution does not contain target")
    elif ecosystem in ("maven", "java"):
        if (root / "pom.xml").exists():
            output = checked(["mvn", "-B", "-ntp", "dependency:tree", f"-Dincludes={package}"], root)
            if not re.search(re.escape(package) + r":[^:\s]+:(?:[^:\s]+:)?" + re.escape(target) + r":", output):
                raise ValueError("Maven resolved dependency differs from target")
        else:
            lock = root / "gradle.lockfile"
            if not lock.exists() or not re.search(r"(?m)^" + re.escape(package + ":" + target) + "=", lock.read_text()):
                raise ValueError("Gradle lockfile does not contain target")
    elif ecosystem in ("nuget", "dotnet"):
        lock = json.loads((root / "packages.lock.json").read_text())
        entries = [entry for framework in lock.get("dependencies", {}).values() for name, entry in framework.items() if name.lower() == package.lower()]
        if not entries or any(entry.get("resolved") != target or not entry.get("contentHash") for entry in entries):
            raise ValueError("NuGet lockfile target mismatch")
    else:
        raise ValueError("Unrecognized ecosystem")
    # Native managers can create their first lockfile. Include only recognized
    # lock artifacts in the review patch; never stage arbitrary generated files.
    for filename in ("go.sum", "Cargo.lock", "uv.lock", "poetry.lock", "gradle.lockfile", "packages.lock.json"):
        path = root / filename
        if path.is_file():
            checked(["git", "add", "--intent-to-add", "--", str(path)])
    return [str(root.relative_to(Path.cwd().resolve()))]
