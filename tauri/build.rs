fn main() {
    tauri_build::build();
    // Link the LocalAuthentication framework so `LAContext` symbols
    // resolve under both `cargo build` and `cargo tauri build`.
    #[cfg(target_os = "macos")]
    {
        println!("cargo:rustc-link-lib=framework=LocalAuthentication");
        println!("cargo:rustc-link-lib=framework=Security");
    }
}
