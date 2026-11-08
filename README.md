# CodeCraft starter

A ready-to-submit strategy for **CodeCraft**, the bot-programming game of 2020, in every language the
[CodeCraft](https://codecraft.day) server accepts. Clone it, pick your language, make it yours.

Each folder is the official 2020 client for that language (the game model, the protocol, the runner)
with the same starter strategy dropped in. The strategy is about a hundred lines and does the same thing
everywhere:

- builders gather resources, repair damaged or unfinished buildings next to them, put up houses when the
  population is nearly full and build the bases that Round 2 starts without;
- the bases train units: builders first, then the fighting bases spend first;
- fighting units wait at home until there are eight of them, then hunt the nearest enemy, shooting whatever
  comes into range.

It beats the engine's built-in QuickStart bot in Round 1 and Round 2, and loses to anything that thinks. The
constants at the top of the strategy file (`FIRST_BUILDERS`, `MAX_BUILDERS`, `ARMY_SIZE`, `REPAIR_RANGE`)
are the first things to play with; the branches of the main loop are the second.

| Language on the submit page | Folder | Strategy file |
|---|---|---|
| C++ | `cpp/` | `MyStrategy.cpp` |
| C# | `csharp/` | `MyStrategy.cs` |
| D | `dlang/` | `source/my_strategy.d` |
| F# | `fsharp/` | `MyStrategy.fs` |
| Go | `go/` | `my_strategy.go` |
| Java, Java (GraalVM native) | `java/`, `java-graalvm-native/` | `src/main/java/MyStrategy.java` |
| JavaScript | `javascript/` | `my-strategy.js` |
| Kotlin, Kotlin (GraalVM native) | `kotlin/`, `kotlin-graalvm-native/` | `src/main/kotlin/MyStrategy.kt` |
| Python, Python (PyPy) | `python/` | `my_strategy.py` |
| Ruby | `ruby/` | `my_strategy.rb` |
| Rust | `rust/` | `src/my_strategy.rs` |
| Scala | `scala/` | `src/main/scala/MyStrategy.scala` |

## Submit it

On [codecraft.day/submit](https://codecraft.day/submit) you name your strategy,
**choose the language** and give the source in one of three ways. The language you choose is what decides
which folder is built.

1. **Git URL.** Paste `https://github.com/format37/codecraft-starter` (better: your fork of it) and pick a
   language. A repository with one folder per language is built from the folder named after the language
   (`python-pypy` falls back to `python/`). A branch, tag or commit can be given next to the URL.
2. **Zip.** Zip one language folder, or the whole repository, and upload it.
3. **One file.** Upload just the strategy file (`my_strategy.py`, `MyStrategy.java`, ...); the server puts it
   into the official client of the chosen language.

Submitting again under the same strategy name makes a new version; the latest successful build plays.

## Make it yours

Fork, change the strategy file of your language, push, submit the fork's URL. The rules of the game, the
whole entity model and the local runner (where you watch your strategy play against QuickStart on your own
machine, in the browser) are in the [server repository](https://github.com/format37/codecraft):
`docs/doc-en.md`, `sim-cpp/`. To run locally, build and start the runner (`make -C sim-cpp`, then
`sim-cpp/build/codecraft-sim-cpp`), pick a TCP seat on port 31001 and start your strategy with
`127.0.0.1 31001` as its arguments (each client's runner takes `host port`, and an optional token).

Only the strategy file is yours to edit: the rest of each folder is the client, and the server builds every
folder exactly like the 2020 contest did (`compile.sh` of the official client, then `run.sh`).

## Licence

The clients are the official ones from [the original repository](https://github.com/MailRuChamps/raic-2020),
GPL-3.0; this repository keeps that licence ([LICENSE](LICENSE)). The starter strategy is by the CodeCraft
maintainers; do what you like with it.
