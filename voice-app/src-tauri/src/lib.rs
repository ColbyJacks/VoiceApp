//! Tauri shell for Voice App.
//!
//! The window is plain HTML/JS (../ui). All audio work happens in the Python
//! voice engine, which this shell starts as a child process and talks to over
//! stdin/stdout with one JSON message per line:
//!
//! - `engine_start` launches the engine (no-op if it is already running).
//! - `engine_send(line)` writes one request line to it.
//! - every line it prints arrives in the UI as an `engine-line` event, and
//!   `engine-exit` fires (with the end of its log) if it stops.

use std::collections::VecDeque;
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Emitter, Manager, RunEvent, State};

const ENGINE_EXE: &str = if cfg!(windows) { "voiceapp-engine.exe" } else { "voiceapp-engine" };

#[derive(Default)]
struct EngineProc {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
}

#[derive(Clone, serde::Serialize)]
struct ExitInfo {
    code: Option<i32>,
    log_tail: String,
}

/// Where the engine lives, in order:
/// 1. `VOICEAPP_ENGINE_PYTHON`: a python.exe with torch installed; runs the
///    engine from this repo's sources (for development).
/// 2. `engine/voiceapp-engine.exe` next to the app (portable folder).
/// 3. `engine/voiceapp-engine.exe` in the installer's resources.
fn engine_command(app: &AppHandle) -> Result<Command, String> {
    if let Ok(python) = std::env::var("VOICEAPP_ENGINE_PYTHON") {
        let repo = std::env::var("VOICEAPP_REPO")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join(".."));
        let sep = if cfg!(windows) { ";" } else { ":" };
        let pythonpath = format!(
            "{}{sep}{}",
            repo.join("core").join("src").display(),
            repo.join("voiceapp").join("engine").join("src").display()
        );
        let mut cmd = Command::new(python);
        cmd.args(["-u", "-m", "voiceapp_engine"]).env("PYTHONPATH", pythonpath);
        return Ok(cmd);
    }

    let mut candidates = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join("engine").join(ENGINE_EXE));
        }
    }
    if let Ok(res) = app.path().resource_dir() {
        candidates.push(res.join("engine").join(ENGINE_EXE));
    }
    for path in &candidates {
        if path.is_file() {
            let mut cmd = Command::new(path);
            if let Some(dir) = path.parent() {
                cmd.current_dir(dir);
            }
            return Ok(cmd);
        }
    }
    Err(format!(
        "The voice engine is missing. Expected it at {}",
        candidates
            .first()
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| ENGINE_EXE.to_string())
    ))
}

fn log_path(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().app_log_dir().ok()?;
    std::fs::create_dir_all(&dir).ok()?;
    Some(dir.join("engine.log"))
}

#[tauri::command]
fn engine_start(app: AppHandle, state: State<'_, EngineProc>) -> Result<(), String> {
    let mut slot = state.child.lock().unwrap();
    if let Some(child) = slot.as_mut() {
        if matches!(child.try_wait(), Ok(None)) {
            return Ok(()); // already running
        }
    }

    let mut cmd = engine_command(&app)?;
    cmd.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    cmd.env("PYTHONIOENCODING", "utf-8");
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("Couldn't start the voice engine: {e}"))?;

    let stdout = child.stdout.take().ok_or("engine has no stdout")?;
    let stderr = child.stderr.take().ok_or("engine has no stderr")?;
    *state.stdin.lock().unwrap() = child.stdin.take();
    *slot = Some(child);

    // stderr: the engine's log (torch warnings, tracebacks). Keep the tail for
    // the error screen and append everything to engine.log.
    let tail: Arc<Mutex<VecDeque<String>>> = Arc::new(Mutex::new(VecDeque::new()));
    let tail_writer = Arc::clone(&tail);
    let log_file = log_path(&app);
    let err_thread = thread::spawn(move || {
        let mut file = log_file.and_then(|p| OpenOptions::new().create(true).append(true).open(p).ok());
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            if let Some(f) = file.as_mut() {
                let _ = writeln!(f, "{line}");
            }
            let mut t = tail_writer.lock().unwrap();
            t.push_back(line);
            if t.len() > 40 {
                t.pop_front();
            }
        }
    });

    let app_out = app.clone();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            let _ = app_out.emit("engine-line", line);
        }
        let _ = err_thread.join();
        let state = app_out.state::<EngineProc>();
        let code = state
            .child
            .lock()
            .unwrap()
            .as_mut()
            .and_then(|c| c.wait().ok())
            .and_then(|s| s.code());
        let log_tail = tail.lock().unwrap().iter().cloned().collect::<Vec<_>>().join("\n");
        let _ = app_out.emit("engine-exit", ExitInfo { code, log_tail });
    });
    Ok(())
}

#[tauri::command]
fn engine_send(line: String, state: State<'_, EngineProc>) -> Result<(), String> {
    let mut stdin = state.stdin.lock().unwrap();
    let pipe = stdin.as_mut().ok_or("The voice engine isn't running")?;
    pipe.write_all(line.trim_end().as_bytes())
        .and_then(|_| pipe.write_all(b"\n"))
        .and_then(|_| pipe.flush())
        .map_err(|e| format!("The voice engine stopped responding: {e}"))
}

#[tauri::command]
fn engine_log_path(app: AppHandle) -> Option<String> {
    log_path(&app).map(|p| p.display().to_string())
}

/// Close the engine's stdin so it stops the audio and exits cleanly; kill it
/// if it hasn't gone after a second.
fn shutdown_engine(app: &AppHandle) {
    let state = app.state::<EngineProc>();
    state.stdin.lock().unwrap().take();
    let child = state.child.lock().unwrap().take();
    if let Some(mut child) = child {
        let deadline = Instant::now() + Duration::from_secs(1);
        while Instant::now() < deadline {
            if matches!(child.try_wait(), Ok(Some(_))) {
                return;
            }
            thread::sleep(Duration::from_millis(50));
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(EngineProc::default())
        .invoke_handler(tauri::generate_handler![engine_start, engine_send, engine_log_path])
        .build(tauri::generate_context!())
        .expect("error while building Voice App")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                shutdown_engine(app);
            }
        });
}
