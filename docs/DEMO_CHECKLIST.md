# Demo checklist

Run through this at least 1 hour before submission, and again before presenting.

## Demo works
- [ ] Demo runs end to end on the **presenting laptop** (not just a teammate's)
- [ ] Seeded, realistic data loaded (no "test123", no empty states on the happy path)
- [ ] Happy-path script written (/demo-script) and rehearsed with a timer, under 2:00
- [ ] Each risky step has a fallback line in the script
- [ ] Browser: zoom set, notifications off, other tabs closed, logged in where needed

## Fallbacks
- [ ] Backup video recorded (full happy path, with voiceover) and playable offline
- [ ] Wifi fallback ready: deployed URL works (`just deploy`), or `just tunnel` tested
- [ ] Deployed URL tested on phone data / another network
- [ ] API keys and rate limits OK for demo traffic; cached/mock response ready if an API dies

## Submission
- [ ] Devpost fields complete (docs/DEVPOST.md copied in): pitch, story, built-with tags, video, links, team members added
- [ ] README.md complete, with every framework/library listed under "Built with"
- [ ] No secrets in the repo (`git log -p | grep -iE "api[_-]?key|secret|token"` is clean)
- [ ] Repo made public: `gh repo edit --visibility public --accept-visibility-change-consequences`
- [ ] Repo renamed to the project name: `gh repo rename <name>`
- [ ] Submitted before the deadline (aim for 30+ minutes early)
