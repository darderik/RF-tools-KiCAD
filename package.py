import os
import shutil
import zipfile

# Folder that shall be put in packaging/plugins
plugins_folders = [
    "rf_tools_wizards",
    "round_tracks",
    "trace_solder_expander",
    "taper_fz",
    "tracks_length",
    "via_fence_generator",
    "trace_clearance",]
plugins_files = [
    "__init__.py",
    "LICENSE",
    "README.md",]
#Files that shall be put in packaging/
root_files = [
    "metadata.json",]

resources_files = [
    "resources\\icon.png",]

def copytree(src, dst, symlinks=False, ignore=None):
    os.makedirs(dst, exist_ok=True)
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            if os.path.exists(d):
                shutil.rmtree(d)
            shutil.copytree(s, d, symlinks, ignore)
        else:
            shutil.copy2(s, d)


# Copy plugins_folders in packaging/plugins/
for folder in plugins_folders:
    if os.path.exists(folder):
        shutil.copytree(folder, os.path.join("packaging/plugins", folder), dirs_exist_ok=True)
# Copy plugins_files in packaging/plugins/
for file in plugins_files:
    if os.path.exists(file):
        shutil.copy2(file, os.path.join("packaging/plugins", file))
# Copy root_files in packaging/
for file in root_files:
    if os.path.exists(file):
        shutil.copy2(file, os.path.join("packaging", file))
# Copy resources_files in packaging/resources/
for file in resources_files:
    if os.path.exists(file):
        shutil.copy2(file, os.path.join("packaging/resources", os.path.basename(file)))

# Create zip file of packaging contents
with zipfile.ZipFile('rftools.zip', 'w', zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk('packaging'):
        for file in files:
            zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), 'packaging'))