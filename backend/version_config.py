"""
Application version and update-check configuration.

Update APP_VERSION before every public release.
"""

APP_VERSION = "2.2"

# Public JSON endpoint used by the app to check for updates.
# Recommended JSON format:
# {
#   "latest_version": "2.2",
#   "changelog": "Short release notes",
#   "downloads": {
#     "windows": {
#       "url": "https://example.com/SchoolManager_Setup.exe"
#     },
#     "macos": {
#       "url": "https://example.com/SchoolManager.dmg"
#     },
#     "macos_arm64": {
#       "url": "https://example.com/SchoolManager-macOS-arm64.dmg"
#     },
#     "macos_intel": {
#       "url": "https://example.com/SchoolManager-macOS-intel.dmg"
#     }
#   }
# }
#
# Legacy Windows-only format is still supported:
# {
#   "latest_version": "2.2",
#   "download_url": "https://example.com/SchoolManager_Setup.exe",
#   "changelog": "Short release notes"
# }
UPDATE_CHECK_URL = "https://gist.githubusercontent.com/maksimelyann1/be8df29696ab683d4ee755e61b9c04ea/raw/gistfile1.txt"
