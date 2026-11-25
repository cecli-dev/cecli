//! Minimal bridge server binary for integration tests.
//!
//! Serves [`ce_app_bridge::default_backend`], which is the fake backend when
//! `CECLI_BRIDGE_BACKEND=fake` and the native backend otherwise. It stays in
//! the foreground so a test harness can own the process lifetime.

fn main() {
    std::process::exit(ce_app_bridge::run_bridge(true));
}
