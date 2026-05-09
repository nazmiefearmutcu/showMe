//! NSStatusItem (menubar tray) — live ticker.
//!
//! Round 12 shipped a static menu (open / scan / alerts / quit). Round 16
//! adds three live items kept in sync with the Python sidecar's
//! `/api/sidecar/ticker` endpoint, polled every 5 s on a background task:
//!
//!   • Bot status (RUNNING/STOPPED) + cycle counter
//!   • Portfolio market value + position count
//!   • Active alerts (mirrored to the dock badge)
//!
//! Each line is a disabled menu item — they're informational, not clickable.
//! When `alerts.active` changes we set the dock badge via `dock::set_badge`.

use crate::{dock, AppState};
use parking_lot::Mutex;
use serde::Deserialize;
use std::sync::Arc;
use std::time::Duration;
use tauri::menu::{MenuBuilder, MenuItemBuilder, MenuItem};
use tauri::tray::{TrayIconBuilder, TrayIconEvent};
use tauri::{App, AppHandle, Emitter, Manager, Runtime, Wry};

#[derive(Default)]
struct TickerHandles {
    bot: Option<MenuItem<Wry>>,
    portfolio: Option<MenuItem<Wry>>,
    alerts: Option<MenuItem<Wry>>,
    last_alerts_active: i64,
}

static TICKER: once_cell::sync::Lazy<Arc<Mutex<TickerHandles>>> =
    once_cell::sync::Lazy::new(|| Arc::new(Mutex::new(TickerHandles::default())));

#[derive(Debug, Deserialize, Default)]
struct Ticker {
    bot: BotState,
    portfolio: PortfolioState,
    alerts: AlertsState,
}

#[derive(Debug, Deserialize, Default)]
struct BotState {
    running: bool,
    cycle: Option<i64>,
    mode: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
struct PortfolioState {
    n_positions: i64,
    market_value: Option<f64>,
}

#[derive(Debug, Deserialize, Default)]
struct AlertsState {
    active: i64,
    fired_today: i64,
}

pub fn install(app: &App) -> tauri::Result<()> {
    let open_item = MenuItemBuilder::with_id("tray.open", "Open showMe").build(app)?;
    let scan_item = MenuItemBuilder::with_id("tray.scan", "Scan now").build(app)?;
    let alerts_item = MenuItemBuilder::with_id("tray.alerts", "Alerts").build(app)?;
    let quit_item = MenuItemBuilder::with_id("tray.quit", "Quit showMe").build(app)?;

    // Live items — disabled (informational). We mutate text via setText().
    let bot_item: MenuItem<Wry> = MenuItemBuilder::with_id("tray.live.bot", "Bot · …")
        .enabled(false)
        .build(app)?;
    let portfolio_item: MenuItem<Wry> =
        MenuItemBuilder::with_id("tray.live.portfolio", "Portfolio · …")
            .enabled(false)
            .build(app)?;
    let alerts_live: MenuItem<Wry> =
        MenuItemBuilder::with_id("tray.live.alerts", "Alerts · …")
            .enabled(false)
            .build(app)?;

    let menu = MenuBuilder::new(app)
        .items(&[&open_item, &scan_item, &alerts_item])
        .separator()
        .items(&[&bot_item, &portfolio_item, &alerts_live])
        .separator()
        .items(&[&quit_item])
        .build()?;

    {
        let mut t = TICKER.lock();
        t.bot = Some(bot_item);
        t.portfolio = Some(portfolio_item);
        t.alerts = Some(alerts_live);
    }

    let _ = TrayIconBuilder::with_id("showme-tray")
        .menu(&menu)
        .icon(app.default_window_icon().unwrap().clone())
        .icon_as_template(true)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "tray.open" => {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }
            "tray.scan" => {
                let _ = Emitter::emit(app, "scan:run", ());
            }
            "tray.alerts" => {
                let _ = Emitter::emit(app, "nav:open", "/alerts");
            }
            "tray.quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { .. } = event {
                let _ = Emitter::emit(tray.app_handle(), "tray:click", ());
            }
        })
        .build(app)?;

    spawn_ticker(app.handle().clone());
    Ok(())
}

fn spawn_ticker<R: Runtime>(handle: AppHandle<R>) {
    tauri::async_runtime::spawn(async move {
        // Wait one beat so the sidecar has a chance to bind.
        tokio::time::sleep(Duration::from_secs(2)).await;
        loop {
            let port = *handle.state::<AppState>().sidecar_port.read();
            if let Some(port) = port {
                if let Ok(t) = fetch_ticker(port).await {
                    apply_ticker(&handle, &t);
                }
            }
            tokio::time::sleep(Duration::from_secs(5)).await;
        }
    });
}

async fn fetch_ticker(port: u16) -> Result<Ticker, String> {
    let url = format!("http://127.0.0.1:{port}/api/sidecar/ticker");
    let resp = reqwest::get(&url).await.map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("status {}", resp.status()));
    }
    resp.json::<Ticker>().await.map_err(|e| e.to_string())
}

fn apply_ticker<R: Runtime>(handle: &AppHandle<R>, ticker: &Ticker) {
    let mut t = TICKER.lock();
    if let Some(item) = &t.bot {
        let label = format!(
            "Bot · {} · {} · cycle {}",
            if ticker.bot.running { "RUNNING" } else { "STOPPED" },
            ticker.bot.mode.as_deref().unwrap_or("mode —"),
            ticker.bot.cycle.map(|c| c.to_string()).unwrap_or_else(|| "—".into()),
        );
        let _ = item.set_text(label);
    }
    if let Some(item) = &t.portfolio {
        let mv = ticker.portfolio.market_value.unwrap_or(0.0);
        let label = format!(
            "Portfolio · {} pos · ${}",
            ticker.portfolio.n_positions,
            format_compact(mv),
        );
        let _ = item.set_text(label);
    }
    if let Some(item) = &t.alerts {
        let label = format!(
            "Alerts · {} active · {} today",
            ticker.alerts.active, ticker.alerts.fired_today
        );
        let _ = item.set_text(label);
    }
    if ticker.alerts.active != t.last_alerts_active {
        t.last_alerts_active = ticker.alerts.active;
        if ticker.alerts.active > 0 {
            dock::set_badge(handle, Some(ticker.alerts.active));
        } else {
            dock::set_badge(handle, None);
        }
    }
}

fn format_compact(n: f64) -> String {
    let abs = n.abs();
    if abs >= 1.0e9 {
        format!("{:.2}B", n / 1.0e9)
    } else if abs >= 1.0e6 {
        format!("{:.2}M", n / 1.0e6)
    } else if abs >= 1.0e3 {
        format!("{:.1}K", n / 1.0e3)
    } else {
        format!("{:.0}", n)
    }
}
