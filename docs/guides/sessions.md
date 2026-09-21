# Sessions
Use `/sessions` to browse sessions, with the latest at the bottom. Click a session
or enter `/sessions ID`, then confirm with Y to resume or N/Esc to cancel.
Use `/new` inside chat for a fresh session in the same repository and execution
mode. The previous session remains available through `/sessions`.
Use `/diff` for agent `edit` and `write` changes on the active conversation
branch. Bash file changes in either mode are outside `/diff`, `/undo`, and
`/apply` tracking.
`/undo` and `/redo` move
the active conversation branch and restore the latest completed turn's files;
if edits overlap, use the reported conflict paths to review them before choosing
`/undo force` or `/redo force`. In a sandbox session, `/apply` merges recorded
agent edits into the source checkout and `/apply force` replaces conflicting files.

Manage previous sessions and apply changes:
```bash
echo-ai sessions             # List this repository
echo-ai sessions --all       # Include other repositories and review sessions
echo-ai chat --resume        # Resume latest non-empty chat in this repository
echo-ai resume               # Same as chat --resume; optionally pass an ID
echo-ai diff <SESSION_ID>                # Recorded agent tool changes
echo-ai diff <SESSION_ID> --output changes.txt # Export change history
echo-ai run "Explain this project"  # Non-interactive task
echo-ai chat --sandbox       # run tools / edits in sandbox
echo-ai chat --sandbox --sandbox-image my-project-sandbox:local
```

