//! Platform-free dialog classification shared by the native window enumerators.

/// Windows class names used by common modal dialogs.
const WINDOWS_DIALOG_CLASSES: [&str; 3] = ["#32770", "NUIDialog", "MsoDlg"];

/// True when a Windows window class belongs to a dialog.
pub fn class_is_dialog(class_name: &str) -> bool {
    let class_name = class_name.trim();

    WINDOWS_DIALOG_CLASSES
        .iter()
        .any(|candidate| candidate.eq_ignore_ascii_case(class_name))
        || class_name.to_ascii_lowercase().starts_with("msodlg")
}

/// True when an AT-SPI role or window type describes a dialog.
pub fn atspi_role_is_dialog(role: &str) -> bool {
    let role = role.trim().to_ascii_lowercase();

    matches!(
        role.as_str(),
        "dialog" | "alert" | "file chooser" | "color chooser" | "font chooser" | "window.dialog"
    ) || role.ends_with("dialog")
        || role.ends_with(" chooser")
}

/// True when a macOS accessibility subrole describes a dialog or sheet.
pub fn subrole_is_dialog(subrole: &str) -> bool {
    matches!(
        subrole.trim().to_ascii_lowercase().as_str(),
        "axdialog" | "axsheet" | "axsystemdialog"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn windows_dialog_classes_are_recognized() {
        assert!(class_is_dialog("#32770"));
        assert!(class_is_dialog("NUIDialog"));
        assert!(class_is_dialog("MsoDlg"));
        assert!(class_is_dialog("MsoDlgOwner"));
        assert!(!class_is_dialog("Chrome_WidgetWin_1"));
        assert!(!class_is_dialog(""));
    }

    #[test]
    fn atspi_roles_cover_dialogs_and_choosers() {
        assert!(atspi_role_is_dialog("dialog"));
        assert!(atspi_role_is_dialog("alert"));
        assert!(atspi_role_is_dialog("File Chooser"));
        assert!(atspi_role_is_dialog("window.dialog"));
        assert!(!atspi_role_is_dialog("frame"));
        assert!(!atspi_role_is_dialog("push button"));
    }

    #[test]
    fn macos_subroles_cover_dialogs_and_sheets() {
        assert!(subrole_is_dialog("AXDialog"));
        assert!(subrole_is_dialog("AXSheet"));
        assert!(subrole_is_dialog("AXSystemDialog"));
        assert!(!subrole_is_dialog("AXStandardWindow"));
        assert!(!subrole_is_dialog(""));
    }
}
