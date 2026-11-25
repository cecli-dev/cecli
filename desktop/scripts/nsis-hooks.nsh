; NSIS installer hooks for ce-underscore.
;
; Wired through `bundle.windows.nsis.installerHooks` in
; tauri.release.conf.json. The bridge must be stopped before $INSTDIR is
; overwritten; a missing bridge is success. The post-install hook then checks
; that a leftover bridge.json matches the newly installed binary and shows a
; clear message on version skew. The PATH entry is opt-in: set
; CECLI_ADD_TO_PATH=1 before running the installer.

!include "LogicLib.nsh"
!include "FileFunc.nsh"

!macro NSIS_HOOK_PREINSTALL
  ${If} ${FileExists} "$INSTDIR\ce-underscore.exe"
    DetailPrint "Stopping the app-harness bridge before replacing files"
    nsExec::ExecToLog '"$INSTDIR\ce-underscore.exe" --stop-bridge'
    Pop $0
    ${If} $0 != 0
      DetailPrint "ce-underscore --stop-bridge returned $0 (a missing bridge is fine)"
    ${EndIf}
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ${If} ${FileExists} "$INSTDIR\_up_\scripts\stop_bridge_before_update.ps1"
    nsExec::ExecToLog 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\_up_\scripts\stop_bridge_before_update.ps1" -Action install -InstallDir "$INSTDIR"'
    Pop $0
    ${If} $0 != 0
      MessageBox MB_ICONSTOP "ce-underscore was installed, but the app-harness version check failed (exit $0). Stop the old bridge with: ce-underscore --stop-bridge"
      SetErrorLevel 1
    ${EndIf}
  ${Else}
    DetailPrint "stop_bridge_before_update.ps1 is missing; skipping the version check"
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ${If} ${FileExists} "$INSTDIR\_up_\scripts\stop_bridge_before_update.ps1"
    nsExec::ExecToLog 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\_up_\scripts\stop_bridge_before_update.ps1" -Action uninstall -InstallDir "$INSTDIR"'
    Pop $0
  ${EndIf}
!macroend
