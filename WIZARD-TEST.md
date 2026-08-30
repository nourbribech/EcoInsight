# Quick Wizard Test

> **Superseded — kept as a record of the session that found the real cause.**
>
> The wizard was invisible for two reasons neither of these steps would have
> found: the frontend bundle had not been rebuilt after the change, and
> `it_wizard_completed` was already set in the database. See the troubleshooting
> table in [DEMO-setup.md](DEMO-setup.md) for the current answer, and note that
> the wizard can now be reopened from the IT setup panel without touching the
> database at all.

## If you see the wizard:
- 4-step interface with progress dots at the top ✓
- Step 1 says "Welcome to EcoInsight IT Setup"
- Back/Next buttons on each step
- Last step says "Go to calibration panel"

## If you don't see the wizard:

### 1. Check you're on the right tab
- Open http://127.0.0.1:8052
- Click the **"IT setup"** tab in the top navigation

### 2. Force refresh the page
- Press Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)
- This clears browser cache and reloads everything

### 3. Check the browser console
- Press F12 to open Developer Tools
- Click the "Console" tab
- Look for any red error messages

### 4. Verify the API is returning wizard data
Open a new terminal and run:
```powershell
curl http://127.0.0.1:8052/api/session | findstr "it_wizard_completed"
```

Should show: `"it_wizard_completed": false`

If it shows `true`, the wizard was already completed. Reset it:
```powershell
cd backend
.\.venv\Scripts\python.exe -c "from GreenIT.database import settings_store; settings_store.set('it_wizard_completed', None); print('wizard reset')"
```

Then reload the page.

### 5. Still not seeing it?
The SetupView component checks:
- `session.mode === 'it'` ✓
- `!wizardDone` (wizard_completed is false) ✓
- Then renders `<ITSetupWizard>`

If you still don't see it after checking above, check the browser console for errors.
