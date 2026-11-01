// A double-clicked desktop build must not open a console, including debug builds.
#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

fn main() {
    showme_lib::run()
}
