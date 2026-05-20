//! NSMenuBar — top of screen menu.
//!
//! Apple HIG: app / File / Edit / View / Window / Help. Round 12 wired the
//! skeleton; UI-INT-08 P2 fleshes it out with cockpit-grade actions.
//!
//! All menu items emit a Tauri event (or invoke a built-in `PredefinedMenuItem`)
//! so the React shell stays the single source of truth for navigation; the
//! native bar just dispatches.

use tauri::menu::{
    AboutMetadataBuilder, MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder,
};
use tauri::App;

pub fn install(app: &App) -> tauri::Result<()> {
    let about_meta = AboutMetadataBuilder::new()
        .name(Some("showMe"))
        .version(Some(env!("CARGO_PKG_VERSION")))
        .copyright(Some("© 2026 showMe"))
        .build();

    // ── App menu ────────────────────────────────────────────────────────
    let app_menu = SubmenuBuilder::new(app, "showMe")
        .item(&PredefinedMenuItem::about(app, Some("About showMe"), Some(about_meta))?)
        .separator()
        .item(
            &MenuItemBuilder::with_id("app.preferences", "Preferences…")
                .accelerator("CmdOrCtrl+,")
                .build(app)?,
        )
        .item(
            &MenuItemBuilder::with_id("app.check_updates", "Check for Updates…").build(app)?,
        )
        .separator()
        .item(&PredefinedMenuItem::services(app, None)?)
        .separator()
        .item(&PredefinedMenuItem::hide(app, None)?)
        .item(&PredefinedMenuItem::hide_others(app, None)?)
        .item(&PredefinedMenuItem::show_all(app, None)?)
        .separator()
        .item(&PredefinedMenuItem::quit(app, None)?)
        .build()?;

    // ── File menu ───────────────────────────────────────────────────────
    let file_menu = SubmenuBuilder::new(app, "File")
        .item(
            &MenuItemBuilder::with_id("file.new_window", "New Window")
                .accelerator("CmdOrCtrl+N")
                .build(app)?,
        )
        .item(
            &MenuItemBuilder::with_id("file.open_palette", "Open Command Palette")
                .accelerator("CmdOrCtrl+K")
                .build(app)?,
        )
        .separator()
        .item(
            &MenuItemBuilder::with_id("file.open_data_folder", "Open Data Folder")
                .accelerator("CmdOrCtrl+Shift+D")
                .build(app)?,
        )
        .separator()
        .item(&PredefinedMenuItem::close_window(app, None)?)
        .build()?;

    // ── Edit menu ───────────────────────────────────────────────────────
    let edit_menu = SubmenuBuilder::new(app, "Edit")
        .item(&PredefinedMenuItem::undo(app, None)?)
        .item(&PredefinedMenuItem::redo(app, None)?)
        .separator()
        .item(&PredefinedMenuItem::cut(app, None)?)
        .item(&PredefinedMenuItem::copy(app, None)?)
        .item(&PredefinedMenuItem::paste(app, None)?)
        .item(&PredefinedMenuItem::select_all(app, None)?)
        .build()?;

    // ── View menu ───────────────────────────────────────────────────────
    // `mut` is required in debug builds (the DevTools entry below
    // re-assigns the builder under `#[cfg(debug_assertions)]`) but
    // looks unused under `--release`. The `#[allow(unused_mut)]`
    // attribute silences the false-positive warning so release builds
    // stay at zero warnings (TEST-09 P0 cleanup).
    #[allow(unused_mut)]
    let mut view_builder = SubmenuBuilder::new(app, "View")
        .item(
            &MenuItemBuilder::with_id("view.reload_index", "Reload Function Index")
                .accelerator("CmdOrCtrl+R")
                .build(app)?,
        )
        .item(&MenuItemBuilder::with_id("view.toggle_tray", "Toggle Tray").build(app)?)
        .item(
            &MenuItemBuilder::with_id("view.toggle_palette", "Toggle Command Palette")
                .accelerator("CmdOrCtrl+Shift+P")
                .build(app)?,
        )
        .item(
            &MenuItemBuilder::with_id("view.toggle_sidebar", "Toggle Sidebar")
                .accelerator("CmdOrCtrl+B")
                .build(app)?,
        );

    // Debug-only: surface DevTools toggle. Release builds hide the entry
    // entirely so the renderer cannot enumerate it via the native menu API.
    #[cfg(debug_assertions)]
    {
        view_builder = view_builder.separator().item(
            &MenuItemBuilder::with_id("view.toggle_devtools", "Toggle DevTools")
                .accelerator("CmdOrCtrl+Alt+I")
                .build(app)?,
        );
    }
    let view_menu = view_builder.build()?;

    let window_menu = SubmenuBuilder::new(app, "Window")
        .item(&PredefinedMenuItem::minimize(app, None)?)
        .item(&PredefinedMenuItem::maximize(app, None)?)
        .item(&PredefinedMenuItem::fullscreen(app, None)?)
        .build()?;

    let help_menu = SubmenuBuilder::new(app, "Help")
        .item(&MenuItemBuilder::with_id("help.docs", "showMe Documentation").build(app)?)
        .item(&MenuItemBuilder::with_id("help.shortcuts", "Keyboard Shortcuts").build(app)?)
        .item(
            &MenuItemBuilder::with_id("help.report_issue", "Report Issue…").build(app)?,
        )
        .build()?;

    let menu = MenuBuilder::new(app)
        .items(&[&app_menu, &file_menu, &edit_menu, &view_menu, &window_menu, &help_menu])
        .build()?;
    app.set_menu(menu)?;

    app.on_menu_event(|app, event| {
        let id = event.id().as_ref();
        match id {
            "file.new_window" => {
                let _ = tauri::Emitter::emit(app, "menu:new_window", ());
            }
            "file.open_palette" | "view.toggle_palette" => {
                let _ = tauri::Emitter::emit(app, "palette:toggle", ());
            }
            "file.open_data_folder" => {
                let _ = tauri::Emitter::emit(app, "menu:open_data_folder", ());
            }
            "view.reload_index" => {
                let _ = tauri::Emitter::emit(app, "function-index:reload", ());
            }
            "view.toggle_tray" => {
                let _ = tauri::Emitter::emit(app, "tray:toggle", ());
            }
            "view.toggle_sidebar" => {
                let _ = tauri::Emitter::emit(app, "sidebar:toggle", ());
            }
            #[cfg(debug_assertions)]
            "view.toggle_devtools" => {
                use tauri::Manager;
                if let Some(w) = app.get_webview_window("main") {
                    if w.is_devtools_open() {
                        w.close_devtools();
                    } else {
                        w.open_devtools();
                    }
                }
            }
            "app.preferences" => {
                let _ = tauri::Emitter::emit(app, "nav:open", "/preferences");
            }
            "app.check_updates" => {
                let _ = tauri::Emitter::emit(app, "updater:check_requested", ());
            }
            "help.docs" => {
                let _ = tauri::Emitter::emit(app, "nav:open", "/help");
            }
            "help.shortcuts" => {
                let _ = tauri::Emitter::emit(app, "help:shortcuts", ());
            }
            "help.report_issue" => {
                let _ = tauri::Emitter::emit(app, "help:report_issue", ());
            }
            _ => {}
        }
    });
    Ok(())
}
