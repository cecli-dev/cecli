# Deterministic WinForms fixture for Windows UIA acceptance tests.
#
# The form exposes stable accessibility names so the bridge can address
# controls without depending on label association or control order:
#
#   Text Editor  - multiline edit, Value pattern
#   Save         - enabled button, Invoke pattern
#   Delete       - disabled button, proves fail-closed behavior
#   Password     - password edit, must never return its value
#   Agree        - checkbox, Toggle pattern
#   Status Label - read-only text updated by Save
#
# Set CECLI_FIXTURE_LOG to a writable file to record each Save click.

param(
    [string]$Title = "cecli Harness Fixture"
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = $Title
$form.ClientSize = New-Object System.Drawing.Size(460, 340)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedSingle"
$form.MaximizeBox = $false
$form.MinimizeBox = $true

$heading = New-Object System.Windows.Forms.Label
$heading.Text = "cecli app-harness fixture"
$heading.AccessibleName = "Fixture Heading"
$heading.Location = New-Object System.Drawing.Point(16, 12)
$heading.Size = New-Object System.Drawing.Size(420, 20)
$form.Controls.Add($heading)

$edit = New-Object System.Windows.Forms.TextBox
$edit.Name = "TextEditor"
$edit.AccessibleName = "Text Editor"
$edit.AccessibleDescription = "Primary editable text control"
$edit.Multiline = $true
$edit.AcceptsReturn = $true
$edit.ScrollBars = "Vertical"
$edit.Location = New-Object System.Drawing.Point(16, 40)
$edit.Size = New-Object System.Drawing.Size(420, 120)
$form.Controls.Add($edit)

$save = New-Object System.Windows.Forms.Button
$save.Name = "SaveButton"
$save.AccessibleName = "Save"
$save.Text = "Save"
$save.Location = New-Object System.Drawing.Point(16, 176)
$save.Size = New-Object System.Drawing.Size(90, 30)
$form.Controls.Add($save)

$delete = New-Object System.Windows.Forms.Button
$delete.Name = "DeleteButton"
$delete.AccessibleName = "Delete"
$delete.Text = "Delete"
$delete.Enabled = $false
$delete.Location = New-Object System.Drawing.Point(116, 176)
$delete.Size = New-Object System.Drawing.Size(90, 30)
$form.Controls.Add($delete)

$passwordLabel = New-Object System.Windows.Forms.Label
$passwordLabel.Text = "Password"
$passwordLabel.Location = New-Object System.Drawing.Point(16, 220)
$passwordLabel.Size = New-Object System.Drawing.Size(120, 20)
$form.Controls.Add($passwordLabel)

$password = New-Object System.Windows.Forms.TextBox
$password.Name = "PasswordField"
$password.AccessibleName = "Password"
$password.UseSystemPasswordChar = $true
$password.Location = New-Object System.Drawing.Point(140, 218)
$password.Size = New-Object System.Drawing.Size(200, 22)
$form.Controls.Add($password)

$agree = New-Object System.Windows.Forms.CheckBox
$agree.Name = "AgreeCheckbox"
$agree.AccessibleName = "Agree"
$agree.Text = "Agree"
$agree.Location = New-Object System.Drawing.Point(16, 250)
$agree.Size = New-Object System.Drawing.Size(120, 22)
$form.Controls.Add($agree)

$status = New-Object System.Windows.Forms.Label
$status.Name = "StatusLabel"
$status.AccessibleName = "Status Label"
$status.Text = "Ready"
$status.Location = New-Object System.Drawing.Point(16, 284)
$status.Size = New-Object System.Drawing.Size(420, 40)
$form.Controls.Add($status)

$script:saveCount = 0

$save.Add_Click({
    $script:saveCount++
    $status.Text = "Saved $script:saveCount"

    if ($env:CECLI_FIXTURE_LOG) {
        try {
            [System.IO.File]::AppendAllText(
                $env:CECLI_FIXTURE_LOG,
                "save=$script:saveCount`n"
            )
        } catch {
            $status.Text = "Saved (log failed)"
        }
    }
})

$form.Add_Shown({
    $edit.Focus()
    Write-Output "cecli-fixture:$Title"
    [Console]::Out.Flush()
})

[System.Windows.Forms.Application]::Run($form)
