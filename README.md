# Agentic AI Engineering

This guide walks you through setting up a GCP account, the Google Cloud CLI, and the agentic AI application that we will extend throughout the lecture. Follow all steps in order. By the end you will have the application running locally — a greeting agent will be ready to answer your questions and help you prepare for the upcoming sessions.

## 1. Prerequisites

Install
- [Python 3.15.2](https://www.python.org/downloads/release/python-3152/)
  - **Windows:** check "Add Python to PATH" during installation, or set manually:
    - `PATH` — add `C:\Users\<YOU>\AppData\Local\Programs\Python\Python315\` and `...\Scripts\`
    - `PYTHONPATH` — (optional) path to your project root so imports resolve correctly
  - **macOS / Linux:** Python is typically available on `PATH` automatically after install
- Create a [Google Cloud Platform](https://console.cloud.google.com) account if you don't already have one
- Install [Google Cloud CLI](https://docs.cloud.google.com/sdk/docs/install-sdk) following the instructions in the link.

## 2. Google Cloud Setup

### 2.1 Create a GCP project

1. Go to [Google Cloud Console — New Project](https://console.cloud.google.com/projectcreate)
2. Enter a **Project name** (e.g. `agentic-ai-engineering`)
3. Select a **Billing account** (required for Gemini Enterprise Agent Platform and Cloud Run)
4. Click **Create** and wait for the project to be provisioned
5. Note your **Project ID** (shown below the project name) — you will need it in later steps

> **Tip:** The project ID is immutable and globally unique. It may differ from the project name.

### 2.2 Set a GCP billing limit

1. Open the [Google Cloud Console - Billing](https://console.cloud.google.com/billing)
2. Select the **billing account** linked to your project
3. In the left menu, click **Budgets & Alerts**
4. Click **Create Budget**
5. Choose:
   - **Scope:** Billing account or project
   - **Budget amount:** e.g. $50/month
6. Set **alert thresholds:** 50%, 90%, 100%

This will notify you by email when spending reaches each threshold.


### 2.3 Google Login & Authentication

Initialize gcloud and log in:

```bash
gcloud init
```

List authenticated accounts:

```bash
gcloud auth list
```

If necessary, switch to the correct account:

```bash
gcloud config set account <YOUR_ACCOUNT_EMAIL>
```

Verify the active project:

```bash
gcloud config get-value project
```

Set the active project, if necessary:

```bash
gcloud config set project <PROJECT_ID>
```

Log in and create Application Default Credentials (ADC):

```bash
gcloud auth application-default login
```

Set the ADC quota project, if a corresponding error message appears:

```bash
gcloud auth application-default set-quota-project <PROJECT_ID>
```

> **Note:** The ADC credentials file is saved at:
> - **Windows:** `%APPDATA%\gcloud\application_default_credentials.json`
> - **macOS / Linux:** `~/.config/gcloud/application_default_credentials.json`
>
> Add this path to your `.env` as `GOOGLE_APPLICATION_CREDENTIALS`.

More help: [gcloud CLI cheat sheet](https://docs.cloud.google.com/sdk/docs/cheatsheet)

### 2.4 Create a Cloud Storage bucket

Create a bucket to store agent artifacts:

```bash
gcloud storage buckets create gs://<BUCKET_NAME> \
  --project=<PROJECT_ID> \
  --location=europe-west3 \
  --uniform-bucket-level-access
```

Replace `<BUCKET_NAME>` with a globally unique name (e.g. `agentic-ai-eng-<PROJECT_ID>`), then set it in `.env`:

```env
GOOGLE_CLOUD_STORAGE_BUCKET=<BUCKET_NAME>
```

> **Note:** Bucket names are globally unique across all GCP projects. A common convention is to include your project ID in the name to avoid conflicts.

### 2.5 Enable the Gemini Enterprise Agent Platform API

Enable the [Gemini Enterprise Agent Platform API](https://console.cloud.google.com/apis/enableflow?apiid=aiplatform.googleapis.com) (formerly Vertex AI, service ID `aiplatform.googleapis.com`), or run:

```bash
gcloud services enable aiplatform.googleapis.com --project=<PROJECT_ID>
```


## 3. IDE Setup — VS Code (Recommended)

Install [Visual Studio Code](https://code.visualstudio.com/) and open the project folder.

### 3.1 Create the virtual environment and select the interpreter

VS Code can create the `.venv` and register the Python interpreter in one step — no terminal required:

1. Open the Command Palette: `Ctrl+Shift+P`
2. Type **Python: Create Environment** and press Enter
3. Select **Venv**
4. Select **Python 3.15.2** as the base interpreter
5. When asked which dependencies to install, tick **`pyproject.toml`** — VS Code will install all packages automatically

VS Code sets the new environment as the active interpreter immediately. You will see **('.venv': venv)** in the status bar at the bottom-left. New terminals opened inside VS Code will have the environment activated automatically.

> **Tip:** If the `.venv` already exists (e.g. created with `python -m venv .venv` in the terminal), skip the steps above. Use **Python: Select Interpreter** instead and choose the **('.venv': venv)** entry.

Activate the virtual environment:

**Windows (PowerShell):**
```powershell
& .\.venv\Scripts\Activate.ps1
```

**macOS / Linux (bash / zsh):**
```bash
source .venv/bin/activate
```

### 3.2 AI Coding Assistant — Claude Code in VS Code

[Claude Code](https://code.claude.com/docs/en/vs-code) is the agentic coding assistant we use throughout the lecture. It runs inside VS Code, reads the project, explains code, proposes changes as diffs, and runs commands. It is included with a Claude Pro subscription. You don't need an API key.

> **Note:** This guide covers VS Code only. If you use a different IDE, you are responsible for setting up Claude Code there yourself. The [Claude Code documentation](https://code.claude.com/docs) is a good starting point.

#### Subscribe to Claude Pro with monthly billing

1. Go to [claude.ai](https://claude.ai) and sign up or log in
2. Click your initials or name in the lower-left corner, then **Settings → Billing**
3. Click **Upgrade plan**, then **Get Pro plan**
4. Select the **monthly** billing period
5. Enter your payment details and click **Subscribe**

#### Install the VS Code extension

Requires **VS Code 1.94.0 or later** (check under **Help → About**).

1. Open the Extensions view: `Ctrl+Shift+X` (macOS: `Cmd+Shift+X`)
2. Search for **Claude Code** (publisher: Anthropic, ID `anthropic.claude-code`) and click **Install**
3. If the extension doesn't appear afterwards, run **Developer: Reload Window** from the Command Palette

#### Sign in with your Pro account

1. Open Claude Code: click the **Spark icon** in the editor toolbar (top-right, visible when a file is open) or in the Activity Bar (left). You can also click **✻ Claude Code** in the status bar (bottom-right).
2. Click **Sign in** and complete authorization in the browser using your Claude Pro account
3. Return to VS Code. The **Learn Claude Code** walkthrough appears, and you can reopen it later via **Claude Code: Open Walkthrough**.

See [section 7](#7-working-with-claude-code) for how to use Claude Code.

## 4. Project Setup

With the `.venv` activated (section 3.1), install [uv](https://docs.astral.sh/uv/) into it. You don't need a global uv installation:

```bash
pip install uv
```

Install dependencies and set up the project:

```bash
uv lock
uv sync
uv pip install -e .
```

`uv sync` also installs the `dev` dependency group: pytest and the ADK evaluation tools. The Cloud Run image doesn't include them.

## 5. Configure `.env`

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Required variables:

- `GOOGLE_APPLICATION_CREDENTIALS` — path to your ADC credentials file
- `GOOGLE_CLOUD_PROJECT` — your GCP project ID
- `GOOGLE_CLOUD_STORAGE_BUCKET` — your Cloud Storage bucket name

## 6. Run the Application locally

```bash
uvicorn agentic_ai_main:app --reload --port 8000
```

The application will be available at **http://localhost:8000**. The chat interface is served at the root path `/`.

When you open the chat, the **greeting agent** welcomes you. It is the default agent: a teaching assistant for this lecture. Ask it for help with setting up and running the project, or for resources to prepare for the upcoming sessions.

## 7. Working with Claude Code

### 7.1 Chat with Claude Code

You work with Claude Code through its chat panel:

1. Open the panel (Spark icon or **✻ Claude Code** in the status bar) and type your request in the prompt box at the bottom, e.g. *"Explain how the greeting agent is wired into the FastAPI app"*
2. Press `Enter` to send and `Shift+Enter` for a new line
3. Claude answers in the chat. When it wants to edit a file or run a command, it shows the change in the chat and asks for your approval, depending on the permission mode.

Useful chat features:

- **Context:** Claude automatically sees the open file and any code you have selected in the editor. You can paste images from the clipboard into the prompt box and drag in files while holding `Shift`.
- **Several chats:** each conversation keeps its own history. Use **Open in New Tab** from the Command Palette to work on several tasks in parallel.
- **Session history:** click the **Session history** button at the top of the panel to search, resume, rename or archive earlier chats
- **Slash commands:** type `/` in the prompt box for the command menu, e.g. `/model` to switch the model, `/plan` to plan before editing, `/compact` to free up context in long chats, and `/usage` to check how much of your Pro limit you have used

### 7.2 Using Claude Code in this project

- **Reference files** with `@`, e.g. `@app/agent_repo/greeting_agent/agent.py` or `@app/` for a folder. Press `Alt+K` (macOS: `Option+K`) to insert the current selection with line numbers.
- **Permission modes** (bottom of the prompt box): **Manual** asks before every edit and command. This is a good starting point because you review each change as a side-by-side diff. **Plan** proposes a plan first and waits for your approval.
- **Shortcuts:** `Ctrl+Esc` (macOS: `Cmd+Esc`) toggles focus between the editor and Claude. `Ctrl+Shift+Esc` (macOS: `Cmd+Shift+Esc`) opens Claude in a new tab.
- **Troubleshooting:** run **Claude Code: Show Logs** from the Command Palette.

> **Note:** The extension doesn't add the `claude` command to your terminal. To use Claude Code in the integrated terminal as well, install the [standalone CLI](https://code.claude.com/docs/en/setup).
