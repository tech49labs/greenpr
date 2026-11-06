"""Real dependency-manager acceptance. Select --ecosystem; no remote PRs."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from npm_acceptance import Fixture


def python_acceptance():
    import importlib.metadata
    try:
        host_version = importlib.metadata.version("colorama")
    except importlib.metadata.PackageNotFoundError:
        host_version = None
    with Fixture() as f:
        (f.root / "requirements.txt").write_text("colorama==0.4.5\n")
        (f.root / "verify.py").write_text("import colorama,importlib.metadata,pathlib\nassert importlib.metadata.version('colorama') == pathlib.Path('requirements.txt').read_text().strip().split('==')[1]\nassert colorama.Fore.RED\n")
        f.commit()
        review, receipt = f.remediate("--ecosystem", "pypi", "--package", "colorama", "--target-version", "0.4.6", "--test-cmd", "python verify.py")
        assert receipt["status"] == "verified"
        assert (review / "requirements.txt").read_text().strip() == "colorama==0.4.6"
        assert (f.root / "requirements.txt").read_text().strip() == "colorama==0.4.5"
        try:
            after_version = importlib.metadata.version("colorama")
        except importlib.metadata.PackageNotFoundError:
            after_version = None
        assert host_version == after_version, "Host Python environment changed"
        print("PASS: Python requirement persisted, isolated venv runtime checked, fresh OSV scan, original unchanged")


def go_acceptance():
    with Fixture() as f:
        (f.root / "go.mod").write_text("module example.invalid/greenpr-acceptance\n\ngo 1.22\n\nrequire github.com/google/uuid v1.3.0\n")
        (f.root / "uuid_test.go").write_text('package acceptance\nimport("testing";"github.com/google/uuid")\nfunc TestUUID(t *testing.T){if _,e:=uuid.Parse("550e8400-e29b-41d4-a716-446655440000");e!=nil{t.Fatal(e)}}\n')
        f.run(["go", "mod", "tidy"])
        f.commit()
        review, receipt = f.remediate("--ecosystem", "go", "--package", "github.com/google/uuid", "--target-version", "v1.6.0")
        assert receipt["status"] == "verified"
        assert "v1.6.0" in (review / "go.mod").read_text()
        assert "v1.3.0" in (f.root / "go.mod").read_text()
        print("PASS: Go manifest/checksum persisted, native resolved module checked, behavioral tests and OSV pass")


def rust_acceptance():
    with Fixture() as f:
        (f.root / ".gitignore").write_text("target/\n")
        (f.root / "Cargo.toml").write_text('[package]\nname="greenpr-acceptance"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nitoa="=1.0.10"\n')
        (f.root / "src").mkdir()
        (f.root / "src/lib.rs").write_text('#[test]\nfn format_integer(){assert_eq!(itoa::Buffer::new().format(42),"42");}\n')
        f.run(["cargo", "generate-lockfile"])
        f.commit()
        review, receipt = f.remediate("--ecosystem", "crates.io", "--package", "itoa", "--target-version", "1.0.15")
        assert receipt["status"] == "verified"
        assert "1.0.15" in (review / "Cargo.lock").read_text()
        print("PASS: Cargo manifest+lock checksums, native metadata, behavioral test and OSV pass")


def maven_acceptance():
    with Fixture() as f:
        (f.root / ".gitignore").write_text("target/\n")
        (f.root / "pom.xml").write_text('''<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion><groupId>com.greenpr</groupId><artifactId>acceptance</artifactId><version>1.0</version><properties><maven.compiler.source>17</maven.compiler.source><maven.compiler.target>17</maven.compiler.target></properties><dependencies><dependency><groupId>org.apache.commons</groupId><artifactId>commons-lang3</artifactId><version>3.17.0</version></dependency><dependency><groupId>junit</groupId><artifactId>junit</artifactId><version>4.13.2</version><scope>test</scope></dependency></dependencies></project>''')
        source = f.root / "src/test/java"
        source.mkdir(parents=True)
        (source / "AcceptanceTest.java").write_text('import org.junit.Test;import static org.junit.Assert.*;import org.apache.commons.lang3.StringUtils;public class AcceptanceTest{@Test public void behavior(){assertTrue(StringUtils.isBlank(" "));}}')
        f.commit()
        review, receipt = f.remediate("--ecosystem", "maven", "--package", "org.apache.commons:commons-lang3", "--target-version", "3.18.0")
        assert receipt["status"] == "verified"
        assert "3.18.0" in (review / "pom.xml").read_text()
        print("PASS: Maven POM persisted, resolved tree target, JUnit behavior and OSV pass")


def gradle_acceptance():
    with Fixture() as f:
        (f.root / ".gitignore").write_text(".gradle/\nbuild/\n")
        (f.root / "settings.gradle").write_text("rootProject.name='greenpr-acceptance'\n")
        (f.root / "build.gradle").write_text("plugins { id 'java' }\nrepositories { mavenCentral() }\ndependencies { implementation 'org.apache.commons:commons-lang3:3.17.0'; testImplementation 'junit:junit:4.13.2' }\n")
        source = f.root / "src/test/java"
        source.mkdir(parents=True)
        (source / "AcceptanceTest.java").write_text('import org.junit.Test;import static org.junit.Assert.*;import org.apache.commons.lang3.StringUtils;public class AcceptanceTest{@Test public void behavior(){assertTrue(StringUtils.isBlank(" "));}}')
        f.commit()
        review, receipt = f.remediate("--ecosystem", "maven", "--package", "org.apache.commons:commons-lang3", "--target-version", "3.18.0")
        assert receipt["status"] == "verified"
        assert "org.apache.commons:commons-lang3:3.18.0=" in (review / "gradle.lockfile").read_text()
        print("PASS: Gradle declaration+new tracked lock, behavioral tests and OSV pass")


def dotnet_acceptance():
    with Fixture() as f:
        (f.root / ".gitignore").write_text("bin/\nobj/\n")
        (f.root / "acceptance.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="Newtonsoft.Json" Version="13.0.2" /></ItemGroup></Project>')
        (f.root / "Program.cs").write_text('using Newtonsoft.Json.Linq;var o=JObject.Parse("{\\"count\\":3}");if((int)o["count"]!=3)throw new System.Exception("behavior failed");')
        f.commit()
        review, receipt = f.remediate("--ecosystem", "nuget", "--package", "Newtonsoft.Json", "--target-version", "13.0.3", "--test-cmd", "dotnet run --no-restore")
        assert receipt["status"] == "verified"
        assert "13.0.3" in (review / "packages.lock.json").read_text()
        print("PASS: .NET PackageReference+lock content hash, runtime behavior and OSV pass")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ecosystem", required=True, choices=["python", "go", "rust", "maven", "gradle", "dotnet"])
    args = parser.parse_args()
    globals()[args.ecosystem + "_acceptance"]()
