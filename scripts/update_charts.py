import os
import yaml
import requests
import re
from packaging.version import parse as parse_version, InvalidVersion

CHARTS_DIR = "charts"

def get_latest_tag_dockerhub(repo):
    # Handle official library images e.g. "python" -> "library/python"
    if "/" not in repo:
        repo = f"library/{repo}"

    url = f"https://hub.docker.com/v2/repositories/{repo}/tags?page_size=100"
    try:
        r = requests.get(url)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        tags = [result["name"] for result in data.get("results", [])]

        # Filter out weird tags
        clean_tags = []
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower in ['latest', 'edge', 'nightly', 'master', 'main', 'stable']: continue
            if 'pr-' in tag_lower: continue
            if 'sha-' in tag_lower: continue
            if 'test' in tag_lower: continue
            if 'unstable' in tag_lower: continue

            # Architecture specific suffixes
            if tag_lower.endswith('-arm') or tag_lower.endswith('-arm64') or tag_lower.endswith('-amd64'): continue
            if tag_lower in ['arm', 'arm64', 'amd64']: continue

            # Simple heuristic: must start with a digit or 'v' followed by digit
            if not re.match(r'^v?\d', tag):
                continue

            # Check if valid semver/packaging version
            try:
                parse_version(tag)
                clean_tags.append(tag)
            except InvalidVersion:
                continue

        if not clean_tags:
            return None

        # Sort by version
        clean_tags.sort(key=lambda t: parse_version(t), reverse=True)
        return clean_tags[0]

    except Exception as e:
        print(f"Error fetching tags for {repo}: {e}")
        return None

def bump_version(version_str):
    # Bump patch version
    try:
        # simplistic bump for now, assuming x.y.z
        parts = version_str.split('.')
        if len(parts) >= 3:
            parts[-1] = str(int(parts[-1]) + 1)
            return ".".join(parts)
        else:
            # try to append .1 if it looks like a number
            return version_str + ".1"
    except:
        return version_str

def update_chart(chart_name):
    chart_path = os.path.join(CHARTS_DIR, chart_name)
    values_path = os.path.join(chart_path, "values.yaml")
    chart_yaml_path = os.path.join(chart_path, "Chart.yaml")

    if not os.path.exists(values_path) or not os.path.exists(chart_yaml_path):
        return

    with open(values_path, 'r') as f:
        try:
            values = yaml.safe_load(f)
        except yaml.YAMLError:
            print(f"Error parsing values.yaml for {chart_name}")
            return

    image_config = values.get('image', {})
    image_repo = image_config.get('repository')
    if not image_repo:
        return

    # Handle copyparty specific structure
    if chart_name == "copyparty" and image_config.get('build'):
        image_repo = f"{image_repo}/{image_config.get('build')}"

    # Handle known registries
    if "ghcr.io" in image_repo:
        print(f"Skipping {chart_name}: GHCR not fully supported in this simple script yet")
        return
    if "lscr.io" in image_repo:
         image_repo = image_repo.replace("lscr.io/", "")

    current_app_version = ""
    current_chart_version = ""

    with open(chart_yaml_path, 'r') as f:
        chart_content = f.read()
        try:
            chart_data = yaml.safe_load(chart_content)
        except yaml.YAMLError:
            print(f"Error parsing Chart.yaml for {chart_name}")
            return

        current_app_version = str(chart_data.get('appVersion', ''))
        current_chart_version = str(chart_data.get('version', ''))

    print(f"Checking {chart_name} (Repo: {image_repo}, Current: {current_app_version})")

    latest_tag = get_latest_tag_dockerhub(image_repo)

    if not latest_tag:
        print(f"  Could not find latest tag for {image_repo}")
        return

    print(f"  Latest tag found: {latest_tag}")

    # Compare
    if latest_tag != current_app_version and latest_tag != "latest":
        try:
            if parse_version(latest_tag) > parse_version(current_app_version):
                print(f"  Updating {chart_name} from {current_app_version} to {latest_tag}")

                # Update Chart.yaml using text replacement to preserve comments
                new_chart_version = bump_version(current_chart_version)

                new_content = chart_content
                # specific regex to safely replace appVersion
                new_content = re.sub(f'appVersion: "{re.escape(current_app_version)}"', f'appVersion: "{latest_tag}"', new_content)
                new_content = re.sub(f'appVersion: {re.escape(current_app_version)}', f'appVersion: "{latest_tag}"', new_content)

                # Update version
                new_content = re.sub(f'version: {re.escape(current_chart_version)}', f'version: {new_chart_version}', new_content)

                with open(chart_yaml_path, 'w') as f:
                    f.write(new_content)
            else:
                print(f"  Current version {current_app_version} is newer or equal to {latest_tag}")
        except InvalidVersion:
             print(f"  Version parsing failed for comparison: {current_app_version} vs {latest_tag}")

def main():
    if not os.path.exists(CHARTS_DIR):
        print(f"Charts directory {CHARTS_DIR} not found.")
        return

    for chart_name in os.listdir(CHARTS_DIR):
        if os.path.isdir(os.path.join(CHARTS_DIR, chart_name)):
            try:
                update_chart(chart_name)
            except Exception as e:
                print(f"Failed to update {chart_name}: {e}")

if __name__ == "__main__":
    main()
