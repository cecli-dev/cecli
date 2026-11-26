//! Standalone bridge binary for tests and headless installs.
//!
//! Serves [`ce_app_bridge::default_backend`] in the foreground so a harness can
//! own the process lifetime, mirroring `ce-underscore --app-harness --foreground`
//! without pulling in the desktop shell.

fn main() {
    std::process::exit(ce_app_bridge::run_bridge(true));
}
