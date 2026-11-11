use std::env;

fn main() {
    println!("cargo:rerun-if-env-changed=CECLI_RUNTIME_SPEC");

    let spec = env::var("CECLI_RUNTIME_SPEC").unwrap_or_else(|_| "cecli-dev".to_string());
    println!("cargo:rustc-env=CECLI_RUNTIME_SPEC={spec}");

    tauri_build::build()
}
