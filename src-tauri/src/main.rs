// LocalCut desktop shell (Tauri v2).
// Starts the bundled Python backend as a sidecar on launch and kills it on exit.
// The UI (frontend/dist) talks to the backend at http://127.0.0.1:8000
// (baked in via VITE_API_BASE at build time).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use tauri::{Manager, State};

struct BackendChild(Mutex<Option<tauri_plugin_shell::process::Child>>);

fn kill_backend(state: &State<BackendChild>) {
    if let Some(child) = state.0.lock().unwrap().take() {
        let _ = child.kill();
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let data_dir = app
                .path()
                .app_data_dir()
                .expect("could not resolve app data dir");
            std::fs::create_dir_all(&data_dir).ok();

            let mut ffmpeg_dir = app
                .path()
                .resource_dir()
                .expect("could not resolve resource dir");
            ffmpeg_dir.push("ffmpeg");

            let sidecar = app
                .shell()
                .sidecar("localcut-backend")
                .expect("failed to locate backend sidecar")
                .args([
                    "--port",
                    "8000",
                    "--data-dir",
                    data_dir.to_str().unwrap(),
                    "--ffmpeg-dir",
                    ffmpeg_dir.to_str().unwrap(),
                ]);
            let (_rx, child) = sidecar.spawn().expect("failed to start backend");
            app.manage(BackendChild(Mutex::new(Some(child))));
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                kill_backend(&window.state::<BackendChild>());
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running LocalCut");
}
