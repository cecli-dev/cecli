# Homebrew cask template for ce-underscore.
#
# The cask is the macOS PATH route: `binary` links
# ce-underscore.app/Contents/MacOS/ce-underscore into the Homebrew prefix so the
# bridge modes are reachable as `ce-underscore`. A .dmg has no pre-install hook,
# so preflight/postflight call the shared stop/verify script before and after
# the app bundle is replaced.
#
# Update version and sha256 (or drop sha256 :no_check) when publishing a build.

cask "ce-underscore" do
  version "0.1.0"
  sha256 :no_check

  url "https://github.com/dwash96/cecli/releases/download/v#{version}/ce-underscore-macos-arm64.dmg"
  name "ce-underscore"
  desc "Desktop shell and app-harness bridge for cecli"
  homepage "https://github.com/dwash96/cecli"

  app "ce-underscore.app"
  binary "#{appdir}/ce-underscore.app/Contents/MacOS/ce-underscore"

  preflight do
    system_command "/bin/bash",
                   args: [
                     "#{staged_path}/ce-underscore.app/Contents/Resources/_up_/scripts/stop_bridge_before_update.sh",
                     "stop"
                   ],
                   must_succeed: false
  end

  postflight do
    system_command "/bin/bash",
                   args: [
                     "#{appdir}/ce-underscore.app/Contents/Resources/_up_/scripts/stop_bridge_before_update.sh",
                     "verify"
                   ],
                   must_succeed: true
  end
end
