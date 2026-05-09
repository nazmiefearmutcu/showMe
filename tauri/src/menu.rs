//! NSMenuBar — top of screen menu.
//!
//! Apple HIG: app / File / Edit / View / Window / Help. Round 12 wires the
//! skeleton; per-function shortcuts (⌘K, ⌘1..9) attach in Round 16.

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

    let app_menu = SubmenuBuilder::new(app, "showMe")
        .item(&PredefinedMenuItem::about(app, Some("About showMe"), Some(about_meta))?)
        .separator()
        .item(&MenuItemBuilder::with_id("app.preferences", "Preferences…")
            .accelerator("CmdOrCtrl+,")
            .build(app)?)
        .separator()
        .item(&PredefinedMenuItem::services(app, None)?)
        .separator()
        .item(&PredefinedMenuItem::hide(app, None)?)
        .item(&PredefinedMenuItem::hide_others(app, None)?)
        .item(&PredefinedMenuItem::show_all(app, None)?)
        .separator()
        .item(&PredefinedMenuItem::quit(app, None)?)
        .build()?;

    let file_menu = SubmenuBuilder::new(app, "File")
        .item(&MenuItemBuilder::with_id("file.new_window", "New Window")
            .accelerator("CmdOrCtrl+N")
            .build(app)?)
        .item(&MenuItemBuilder::with_id("file.open_palette", "Open Command Palette")
            .accelerator("CmdOrCtrl+K")
            .build(app)?)
        .separator()
        .item(&PredefinedMenuItem::close_window(app, None)?)
        .build()?;

    let edit_menu = SubmenuBuilder::new(app, "Edit")
        .item(&PredefinedMenuItem::undo(app, None)?)
        .item(&PredefinedMenuItem::redo(app, None)?)
        .separator()
        .item(&PredefinedMenuItem::cut(app, None)?)
        .item(&PredefinedMenuItem::copy(app, None)?)
        .item(&PredefinedMenuItem::paste(app, None)?)
        .item(&PredefinedMenuItem::select_all(app, None)?)
        .build()?;

    let view_menu = SubmenuBuilder::new(app, "View")
        .item(&MenuItemBuilder::with_id("view.reload_index", "Reload Function Index")
            .accelerator("CmdOrCtrl+R")
            .build(app)?)
        .item(&MenuItemBuilder::with_id("view.toggle_tray", "Toggle Tray")
            .build(app)?)
        .item(&MenuItemBuilder::with_id("view.toggle_palette", "Toggle Command Palette")
            .accelerator("CmdOrCtrl+Shift+P")
            .build(app)?)
        .build()?;

    let window_menu = SubmenuBuilder::new(app, "Window")
        .item(&PredefinedMenuItem::minimize(app, None)?)
        .item(&PredefinedMenuItem::maximize(app, None)?)
        .item(&PredefinedMenuItem::fullscreen(app, None)?)
        .build()?;

    let help_menu = SubmenuBuilder::new(app, "Help")
        .item(&MenuItemBuilder::with_id("help.docs", "Documentation").build(app)?)
        .item(&MenuItemBuilder::with_id("help.shortcuts", "Keyboard Shortcuts").build(app)?)
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
            "view.reload_index" => {
                let _ = tauri::Emitter::emit(app, "function-index:reload", ());
            }
            "view.toggle_tray" => {
                let _ = tauri::Emitter::emit(app, "tray:toggle", ());
            }
            "app.preferences" => {
                let _ = tauri::Emitter::emit(app, "nav:open", "/preferences");
            }
            "help.docs" => {
                let _ = tauri::Emitter::emit(app, "nav:open", "/help");
            }
            "help.shortcuts" => {
                let _ = tauri::Emitter::emit(app, "help:shortcuts", ());
            }
            _ => {}
        }
    });
    Ok(())
}
