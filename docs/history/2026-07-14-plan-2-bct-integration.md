# Skill Self-Learning Loop — Plan 2: BCT Integration

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline; Swift build is serial). Steps use `- [ ]`.

**Goal:** Deploy the Plan-1 Python core to `~/.claude/` automatically on BCT launch, and trigger the curator when BCT is globally idle — so the loop is native to BCT with zero manual install.

**Architecture:** A new `SkillLoopDeploy.swift` (a) copies the bundled `scripts/` payload to `~/.claude/scripts/skill-loop/` and runs `bootstrap.py` on launch, mirroring the 7 `*SkillDeploy` trigger; and (b) runs a 60s Timer that reads `StatusbarBridge.shared.panes` — when all panes have been quiet (empty map) for N consecutive ticks it spawns `curator.py` via `Process()`. The Python payload ships as a **bundle folder reference** (like `Resources/vendor` / `bct-rdp`), not embedded Swift strings, so there is no drift and no `SkillLoopSyncTests`.

**Tech Stack:** Swift 6 / AppKit, XcodeGen (`project.yml`), swift-testing (`#expect`), `xcodebuild`.

## Global Constraints

- **New source files auto-included**: `Sources/` is a folder source in `project.yml` — new `.swift` needs no manifest edit. But the **bundle folder reference for the payload IS a manifest edit** → `xcodegen generate` before building.
- **Deploy is XCTest-gated**: like every `*SkillDeploy`, guard `deployAsync()` behind `ProcessInfo…["XCTestConfigurationFilePath"] == nil` so tests/harness don't write to `~/.claude`.
- **Never block launch / main thread**: copy + bootstrap + curator spawn all on `DispatchQueue.global(.utility)` / detached `Process`.
- **Curator spawn respects config**: read `~/.claude/skill-loop.json` `enabled` (default true) and `idle_threshold_minutes` (default 10); the interval guard (24h) is already inside `curator.py`.
- **Payload path**: bundle `Contents/Resources/scripts/` (folder ref of repo `.claude/skill-loop/scripts`) → copy to `~/.claude/scripts/skill-loop/`.

---

### Task 1: Bundle payload + `SkillLoopDeploy` copy/bootstrap on launch

**Files:**
- Modify: `project.yml` (add folder-ref resource for `.claude/skill-loop/scripts`)
- Create: `Sources/SkillLoopDeploy.swift`
- Modify: `Sources/BomiTerminalApp.swift` (add `SkillLoopDeploy.deployAsync()` to the launch chain)

**Interfaces:**
- Produces:
  - `enum SkillLoopDeploy` with:
    - `static func payloadURL() -> URL?` — `Bundle.main.resourceURL?.appendingPathComponent("scripts")`, falling back to `Bundle(for:)` anchor for the test host (mirror `RdpEngineClient`/`StatuslineBinary`).
    - `static func destDir() -> String` — `~/.claude/scripts/skill-loop`.
    - `@discardableResult static func deploy(payload: URL, to dest: String) -> Bool` — recursively copies `payload/*` to `dest` (overwrite: our scripts are not user-edited; replace stale copies), returns success.
    - `static func runBootstrap(dest: String)` — `Process()` `python3 <dest>/bootstrap.py`, detached, best-effort.
    - `static func deployAsync()` — XCTest-gated; on `.utility` queue: `deploy` then `runBootstrap`.

- [ ] **Step 1: Add the folder-ref resource to project.yml**

In the BCT target's `sources:` list (next to `Resources/companions`), add:
```yaml
      - path: .claude/skill-loop/scripts
        type: folder
```
(A folder reference lands the tree at `Contents/Resources/scripts/` without flattening, same as `Resources/vendor`.)

- [ ] **Step 2: Write `SkillLoopDeploy.swift` (copy + bootstrap half only)**

```swift
import Foundation

/// Deploys the skill self-learning loop (Plan 1 Python core) to
/// ~/.claude/scripts/skill-loop/ on launch, then runs bootstrap.py to merge the
/// SessionEnd/PreToolUse hooks into ~/.claude/settings.json. The payload is a
/// bundle folder reference (Contents/Resources/scripts) — no embedded strings,
/// so it never drifts from the repo. Mirrors the 7 *SkillDeploy launch trigger.
enum SkillLoopDeploy {
    static func payloadURL() -> URL? {
        for b in [Bundle.main, Bundle(for: SkillLoopBundleAnchor.self)] {
            if let u = b.resourceURL?.appendingPathComponent("scripts"),
               FileManager.default.fileExists(atPath: u.appendingPathComponent("bootstrap.py").path) {
                return u
            }
        }
        return nil
    }

    static func destDir() -> String {
        (NSHomeDirectory() as NSString).appendingPathComponent(".claude/scripts/skill-loop")
    }

    @discardableResult
    static func deploy(payload: URL, to dest: String) -> Bool {
        let fm = FileManager.default
        do {
            try fm.createDirectory(atPath: dest, withIntermediateDirectories: true)
            for item in try fm.contentsOfDirectory(at: payload, includingPropertiesForKeys: nil) {
                let dst = URL(fileURLWithPath: dest).appendingPathComponent(item.lastPathComponent)
                if fm.fileExists(atPath: dst.path) {
                    if (try? fm.contentsOfDirectory(at: item, includingPropertiesForKeys: nil)) != nil {
                        try? fm.removeItem(at: dst)                 // dir: replace wholesale
                        try fm.copyItem(at: item, to: dst)
                    } else {
                        _ = try? Data(contentsOf: item).write(to: dst)  // file: overwrite
                    }
                } else {
                    try fm.copyItem(at: item, to: dst)
                }
            }
            return true
        } catch { return false }
    }

    static func runBootstrap(dest: String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        p.arguments = ["python3", "\(dest)/bootstrap.py"]
        try? p.run()
    }

    static func deployAsync() {
        guard ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] == nil else { return }
        DispatchQueue.global(qos: .utility).async {
            guard let payload = payloadURL() else { return }
            let dest = destDir()
            if deploy(payload: payload, to: dest) { runBootstrap(dest: dest) }
        }
    }
}

final class SkillLoopBundleAnchor {}
```

- [ ] **Step 3: Wire into the launch chain**

In `Sources/BomiTerminalApp.swift`, after `RdpControlSkillDeploy.deployAsync()`:
```swift
        RdpControlSkillDeploy.deployAsync()
        SkillLoopDeploy.deployAsync()   // deploy the skill self-learning loop + bootstrap hooks
```

- [ ] **Step 4: Regenerate + build**

```bash
xcodegen generate
xcodebuild -scheme BCT -destination 'platform=macOS' build 2>&1 | tail -5
```
Expected: `** BUILD SUCCEEDED **`. (Confirms the folder-ref resource and new source compile.)

- [ ] **Step 5: Commit**

```bash
git add project.yml Sources/SkillLoopDeploy.swift Sources/BomiTerminalApp.swift
git commit -m "feat(skill-loop): SkillLoopDeploy — bundle payload + bootstrap on BCT launch"
```

---

### Task 2: Global-idle curator trigger

**Files:**
- Modify: `Sources/SkillLoopDeploy.swift` (add the idle watcher)
- Test: `Tests/SkillLoopDeployTests.swift`

**Interfaces:**
- Consumes: `StatusbarBridge.shared.panes` (`[UUID: PaneState]`), `SkillLoopDeploy.destDir()`.
- Produces:
  - `static func idleThresholdTicks(configPath: String) -> Int` — `ceil(idle_threshold_minutes*60 / tickSeconds)`, default 10 min → 10 ticks at 60s; disabled (`enabled:false`) → returns 0.
  - `static func shouldTriggerCurator(paneCount: Int, idleTicks: Int, thresholdTicks: Int) -> Bool` — pure: `paneCount == 0 && thresholdTicks > 0 && idleTicks >= thresholdTicks`.
  - `static func startIdleWatcher()` — a 60s repeating Timer (main run-loop) that counts consecutive empty-`panes` ticks; on `shouldTriggerCurator` true, spawns `curator.py` (detached `Process`) and resets the counter.

- [ ] **Step 1: Write the failing tests**

```swift
import Testing
import Foundation
@testable import BCT

struct SkillLoopDeployTests {
    @Test func triggers_only_when_idle_and_enabled() {
        #expect(SkillLoopDeploy.shouldTriggerCurator(paneCount: 0, idleTicks: 10, thresholdTicks: 10) == true)
        #expect(SkillLoopDeploy.shouldTriggerCurator(paneCount: 1, idleTicks: 99, thresholdTicks: 10) == false) // active pane
        #expect(SkillLoopDeploy.shouldTriggerCurator(paneCount: 0, idleTicks: 5,  thresholdTicks: 10) == false) // not idle long enough
        #expect(SkillLoopDeploy.shouldTriggerCurator(paneCount: 0, idleTicks: 10, thresholdTicks: 0)  == false) // disabled
    }

    @Test func threshold_ticks_from_config() throws {
        let dir = NSTemporaryDirectory() + UUID().uuidString
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        let cfg = dir + "/skill-loop.json"
        try #"{"enabled": true, "idle_threshold_minutes": 10}"#.write(toFile: cfg, atomically: true, encoding: .utf8)
        #expect(SkillLoopDeploy.idleThresholdTicks(configPath: cfg) == 10)
        try #"{"enabled": false, "idle_threshold_minutes": 10}"#.write(toFile: cfg, atomically: true, encoding: .utf8)
        #expect(SkillLoopDeploy.idleThresholdTicks(configPath: cfg) == 0)
    }

    @Test func deploy_copies_payload(_ ) throws {
        let fm = FileManager.default
        let src = NSTemporaryDirectory() + UUID().uuidString + "/scripts"
        try fm.createDirectory(atPath: src, withIntermediateDirectories: true)
        try "print('x')".write(toFile: src + "/bootstrap.py", atomically: true, encoding: .utf8)
        let dst = NSTemporaryDirectory() + UUID().uuidString + "/dest"
        #expect(SkillLoopDeploy.deploy(payload: URL(fileURLWithPath: src), to: dst) == true)
        #expect(fm.fileExists(atPath: dst + "/bootstrap.py"))
    }
}
```

- [ ] **Step 2: Run tests to verify they fail (symbols missing)**

```bash
xcodebuild test -scheme BCT -destination 'platform=macOS' -only-testing:BCTTests/SkillLoopDeployTests 2>&1 | tail -8
```
Expected: compile failure — `idleThresholdTicks` / `shouldTriggerCurator` not found.

- [ ] **Step 3: Add the idle watcher to `SkillLoopDeploy.swift`**

```swift
extension SkillLoopDeploy {
    static func configPath() -> String {
        (NSHomeDirectory() as NSString).appendingPathComponent(".claude/skill-loop.json")
    }

    static func idleThresholdTicks(configPath: String, tickSeconds: Double = 60) -> Int {
        guard let data = FileManager.default.contents(atPath: configPath),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return Int((10.0 * 60 / tickSeconds).rounded(.up))   // default 10 min
        }
        if (obj["enabled"] as? Bool) == false { return 0 }
        let mins = (obj["idle_threshold_minutes"] as? NSNumber)?.doubleValue ?? 10
        return max(1, Int((mins * 60 / tickSeconds).rounded(.up)))
    }

    static func shouldTriggerCurator(paneCount: Int, idleTicks: Int, thresholdTicks: Int) -> Bool {
        paneCount == 0 && thresholdTicks > 0 && idleTicks >= thresholdTicks
    }

    @MainActor
    static func startIdleWatcher() {
        guard ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] == nil else { return }
        var idleTicks = 0
        Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in
            let threshold = idleThresholdTicks(configPath: configPath())
            let count = StatusbarBridge.shared.panes.count
            idleTicks = count == 0 ? idleTicks + 1 : 0
            if shouldTriggerCurator(paneCount: count, idleTicks: idleTicks, thresholdTicks: threshold) {
                idleTicks = 0
                DispatchQueue.global(qos: .utility).async {
                    let p = Process()
                    p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
                    p.arguments = ["python3", "\(destDir())/curator.py"]
                    try? p.run()
                }
            }
        }
    }
}
```
And call `SkillLoopDeploy.startIdleWatcher()` in `BomiTerminalApp` right after `StatusbarOverlayComposer.shared.start(bridge: .shared)`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
xcodebuild test -scheme BCT -destination 'platform=macOS' -only-testing:BCTTests/SkillLoopDeployTests 2>&1 | tail -8
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add Sources/SkillLoopDeploy.swift Sources/BomiTerminalApp.swift Tests/SkillLoopDeployTests.swift
git commit -m "feat(skill-loop): global-idle curator trigger via StatusbarBridge panes watcher"
```

---

### Task 3: Full build + live smoke

- [ ] **Step 1: Full test suite (no regressions)**

```bash
xcodebuild test -scheme BCT -destination 'platform=macOS' 2>&1 | tail -6
```
Expected: overall test success (existing suite + SkillLoopDeployTests).

- [ ] **Step 2: Live smoke (real deploy)**

Build + run BCT (Apple-Dev signed per CLAUDE.md), then confirm:
1. `~/.claude/scripts/skill-loop/` populated (scripts + prompts/ + config.default.json).
2. `~/.claude/settings.json` gained the SessionEnd(learn) + PreToolUse(Skill→usage) entries; `~/.claude/skill-loop.json` seeded.
3. A BCT-deployed skill (`terminal-control`, unmarked) still present and untouched.
4. (optional) Leave BCT with no panes for >10 min or lower `idle_threshold_minutes` → confirm `curator.py` runs once (check `~/.claude/skills/.curator_state`).

- [ ] **Step 3: Commit any doc updates**

```bash
git add -A && git commit -m "docs(skill-loop): Plan 2 live-smoke notes"
```

## Self-Review

- Spec ④ deploy → Task 1; StatusbarBridge global-idle trigger → Task 2; (SkillLoopSyncTests replaced by bundle-folder-ref, noted in Plan 1 §Implementation notes — no drift to test). Live smoke → Task 3.
- Placeholder scan: none — all code/commands concrete.
- Type consistency: `SkillLoopDeploy.deploy/deployAsync/destDir/payloadURL/idleThresholdTicks/shouldTriggerCurator/startIdleWatcher` used consistently across Tasks 1–2 and the test.
