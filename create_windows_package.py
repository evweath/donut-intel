#!/usr/bin/env python3
"""
Generate the Windows distribution package:
  - WINDOWS-SETUP-GUIDE.pdf  (user guide)
  - DonutIntel-Windows.zip   (all app files, sanitized config)

Run from the project root with the venv active:
    python create_windows_package.py
"""
import io
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).parent

# ---------------------------------------------------------------------------
# HTML document
# ---------------------------------------------------------------------------

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Donut Intel Platform — Windows Setup &amp; User Guide</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13.5px;
    line-height: 1.65;
    color: #1a1a1a;
    max-width: 860px;
    margin: 0 auto;
    padding: 30px 40px;
  }
  /* ---- Cover ---- */
  .cover {
    text-align: center;
    padding: 80px 40px 60px;
    border-bottom: 4px solid #1a4080;
    margin-bottom: 40px;
  }
  .cover .logo { font-size: 56px; margin-bottom: 10px; }
  .cover h1 {
    font-size: 34px;
    color: #1a4080;
    margin-bottom: 6px;
    letter-spacing: -0.5px;
  }
  .cover .subtitle {
    font-size: 18px;
    color: #555;
    margin-bottom: 30px;
  }
  .cover .meta {
    font-size: 13px;
    color: #888;
    border-top: 1px solid #ddd;
    padding-top: 20px;
    margin-top: 30px;
  }
  /* ---- Headings ---- */
  h1 { font-size: 26px; color: #1a4080; margin: 40px 0 12px; padding-bottom: 8px; border-bottom: 2px solid #1a4080; }
  h2 { font-size: 20px; color: #1a4080; margin: 32px 0 10px; }
  h3 { font-size: 16px; color: #2d5fad; margin: 22px 0 8px; }
  h4 { font-size: 14px; color: #333; margin: 16px 0 6px; font-weight: 700; }
  /* ---- Body text ---- */
  p { margin: 8px 0 12px; }
  /* ---- Lists ---- */
  ol, ul { margin: 8px 0 14px 24px; }
  li { margin: 6px 0; }
  ol li { padding-left: 4px; }
  /* ---- Code ---- */
  code {
    background: #f0f2f5;
    color: #c7254e;
    padding: 1px 5px;
    border-radius: 3px;
    font-family: 'Courier New', Courier, monospace;
    font-size: 12.5px;
  }
  pre {
    background: #1e1e2e;
    color: #cdd6f4;
    padding: 14px 18px;
    border-radius: 7px;
    margin: 12px 0 16px;
    overflow-x: auto;
    font-family: 'Courier New', Courier, monospace;
    font-size: 12.5px;
    line-height: 1.5;
  }
  pre code { background: none; color: inherit; padding: 0; font-size: inherit; }
  /* ---- Call-out boxes ---- */
  .step-box {
    background: #eef4ff;
    border-left: 5px solid #2d5fad;
    border-radius: 0 6px 6px 0;
    padding: 12px 16px;
    margin: 12px 0;
  }
  .warning-box {
    background: #fff8e6;
    border-left: 5px solid #e6a817;
    border-radius: 0 6px 6px 0;
    padding: 12px 16px;
    margin: 12px 0;
  }
  .tip-box {
    background: #edfaf1;
    border-left: 5px solid #28a745;
    border-radius: 0 6px 6px 0;
    padding: 12px 16px;
    margin: 12px 0;
  }
  .info-box {
    background: #f0f6ff;
    border: 1px solid #b8d0f5;
    border-radius: 6px;
    padding: 12px 16px;
    margin: 12px 0;
  }
  .box-title { font-weight: 700; margin-bottom: 4px; }
  /* ---- Feature box ---- */
  .feature {
    border: 1px solid #d0dae8;
    border-radius: 8px;
    padding: 16px 20px;
    margin: 18px 0;
    page-break-inside: avoid;
  }
  .feature-name {
    font-size: 16px;
    font-weight: 700;
    color: #1a4080;
    margin-bottom: 6px;
  }
  .feature-tagline { color: #555; font-style: italic; margin-bottom: 10px; }
  /* ---- Tables ---- */
  table { width: 100%; border-collapse: collapse; margin: 14px 0 18px; font-size: 13px; }
  th { background: #1a4080; color: #fff; padding: 9px 12px; text-align: left; }
  td { padding: 8px 12px; border-bottom: 1px solid #e0e6ef; vertical-align: top; }
  tr:nth-child(even) td { background: #f6f9ff; }
  /* ---- URL styling ---- */
  .url { color: #0052cc; font-weight: 600; word-break: break-all; }
  a { color: #0052cc; }
  /* ---- TOC ---- */
  .toc { background: #f6f9ff; border: 1px solid #c5d8f5; border-radius: 8px; padding: 20px 28px; margin: 20px 0 40px; }
  .toc h2 { margin-top: 0; border: none; font-size: 16px; }
  .toc ol { font-size: 13.5px; }
  .toc li { margin: 4px 0; }
  .toc a { color: #1a4080; text-decoration: none; }
  /* ---- Glossary ---- */
  .gloss-term { font-weight: 700; color: #1a4080; }
  dt { font-weight: 700; color: #1a4080; margin-top: 10px; }
  dd { margin-left: 20px; margin-bottom: 6px; }
  /* ---- Page breaks ---- */
  .page-break { page-break-before: always; }
  .avoid-break { page-break-inside: avoid; }
  /* ---- Numbered step ---- */
  .num-step { display: flex; gap: 12px; align-items: flex-start; margin: 10px 0; }
  .num { background: #1a4080; color: white; border-radius: 50%; min-width: 26px; height: 26px;
         display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px; flex-shrink: 0; }
  .num-content { flex: 1; padding-top: 2px; }
  /* ---- Section label ---- */
  .section-label {
    display: inline-block;
    background: #1a4080;
    color: white;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 2px 8px;
    border-radius: 3px;
    margin-bottom: 6px;
    text-transform: uppercase;
  }
  hr { border: none; border-top: 1px solid #dde4ef; margin: 30px 0; }
</style>
</head>
<body>

<!-- ======================================================== COVER -->
<div class="cover">
  <div class="logo">🍩</div>
  <h1>Donut Intel Platform</h1>
  <div class="subtitle">Windows Setup &amp; User Guide</div>
  <p style="font-size:15px;color:#444;margin-top:16px;">
    A step-by-step guide to installing, setting up,<br>and using the Donut Intel Platform on Windows.
  </p>
  <div class="meta">
    Version 2.0 &nbsp;|&nbsp; Written for Windows 10 and Windows 11<br>
    Read this guide from start to finish before you begin.
  </div>
</div>

<!-- ======================================================== TOC -->
<div class="toc">
  <h2>📋 Table of Contents</h2>
  <ol>
    <li><a href="#s1">Welcome — What Is Donut Intel?</a></li>
    <li><a href="#s2">What You Need Before Starting</a></li>
    <li><a href="#s3">Step 1 — Install Python</a></li>
    <li><a href="#s4">Step 2 — Get the App Files</a></li>
    <li><a href="#s5">Step 3 — Run First-Time Setup</a></li>
    <li><a href="#s6">Step 4 — Configure Your Settings</a></li>
    <li><a href="#s7">Step 5 — Start the App</a></li>
    <li><a href="#s8">Step 6 — Open the App in Your Browser</a></li>
    <li><a href="#s9">Step 7 — Stop the App</a></li>
    <li><a href="#s10">All Features Explained (The Dashboard)</a></li>
    <li><a href="#s11">Command Line Tools (Advanced)</a></li>
    <li><a href="#s12">Automatic Scheduled Tasks</a></li>
    <li><a href="#s13">Troubleshooting</a></li>
    <li><a href="#glossary">Glossary — Words and What They Mean</a></li>
  </ol>
</div>

<!-- ======================================================== SECTION 1 -->
<div class="page-break"></div>
<div class="section-label">Section 1</div>
<h1 id="s1">Welcome — What Is Donut Intel?</h1>

<p>
  <strong>Donut Intel</strong> is a computer program that helps you keep track of products
  and prices across multiple stores on the internet. Think of it like having a
  very smart assistant who visits websites every day, writes down what everything costs,
  and tells you when a competitor is selling something cheaper than you are.
</p>

<h2>What Can It Do?</h2>
<ul>
  <li>📦 <strong>Collect products</strong> — It visits your websites and saves a list of every product you sell, along with its price.</li>
  <li>🏪 <strong>Watch competitors</strong> — It searches the internet for stores that sell the same things you do and records their prices.</li>
  <li>💰 <strong>Compare prices</strong> — It shows you side-by-side price comparisons so you can see if someone is cheaper than you.</li>
  <li>🔁 <strong>Find duplicates</strong> — It notices when the same product is listed more than once and helps you clean up your catalog.</li>
  <li>🛍️ <strong>Connect to Shopify</strong> — It can sync product information directly to your Shopify store.</li>
  <li>⏰ <strong>Run automatically</strong> — You can set it to do all of this on a schedule, so you don't have to remember to run it.</li>
  <li>📤 <strong>Export data</strong> — It can save your product data to a spreadsheet file (Excel or CSV) that you can share with others.</li>
</ul>

<h2>Who Is This Guide For?</h2>
<p>
  This guide is written for anyone setting up Donut Intel on a Windows computer.
  You do <strong>not</strong> need to be a programmer.
  All you need is the ability to follow step-by-step instructions.
  If you can copy files and type commands, you can set this up.
</p>

<div class="info-box">
  <div class="box-title">📖 How to Use This Guide</div>
  Follow the sections in order from top to bottom the first time you set up the app.
  After that, you can jump to any section to look up how to use a specific feature.
</div>

<!-- ======================================================== SECTION 2 -->
<div class="page-break"></div>
<div class="section-label">Section 2</div>
<h1 id="s2">What You Need Before Starting</h1>

<h2>Computer Requirements</h2>
<table>
  <tr><th>Item</th><th>Minimum</th><th>Recommended</th></tr>
  <tr><td>Operating System</td><td>Windows 10 (64-bit)</td><td>Windows 11</td></tr>
  <tr><td>Memory (RAM)</td><td>4 GB</td><td>8 GB or more</td></tr>
  <tr><td>Free Disk Space</td><td>5 GB</td><td>10 GB or more</td></tr>
  <tr><td>Internet Connection</td><td>Required for setup</td><td>Required for all scanning features</td></tr>
  <tr><td>Web Browser</td><td>Edge, Chrome, or Firefox</td><td>Google Chrome</td></tr>
</table>

<div class="warning-box">
  <div class="box-title">⚠️ Important — 64-bit Windows Required</div>
  This app only works on 64-bit versions of Windows. To check yours:
  click the <strong>Start</strong> button, type <strong>About your PC</strong>, press Enter,
  and look for "System type." It should say "64-bit operating system."
</div>

<h2>How Much Time You'll Need</h2>
<ul>
  <li><strong>First-time setup:</strong> About 20–30 minutes (mostly waiting for downloads)</li>
  <li><strong>Configuration:</strong> About 10 minutes</li>
  <li><strong>Learning to use the app:</strong> About 1 hour to read this guide and explore</li>
</ul>

<h2>Helpful Things to Know Beforehand</h2>
<p>
  You will need to know the <strong>username</strong> and <strong>password</strong> you want to use to log into
  the app. The default is <code>admin</code> / <code>changeme</code>, but you will change this during setup.
</p>
<p>
  If you use Shopify or want to search for competitor prices using services like SerpAPI or Anthropic AI,
  you will need your <strong>API keys</strong> from those services.
  An <strong>API key</strong> is like a password that lets the app talk to another service.
  If you don't have these, that's fine — most features work without them.
</p>

<!-- ======================================================== SECTION 3 -->
<div class="page-break"></div>
<div class="section-label">Section 3</div>
<h1 id="s3">Step 1 — Install Python</h1>

<p>
  <strong>Python</strong> is the programming language that Donut Intel is built with.
  Think of it as the "engine" that makes the app run.
  You need to install it before anything else.
</p>

<h2>Download Python</h2>

<div class="step-box">
  <div class="box-title">🌐 Download Python Here:</div>
  <p class="url">https://www.python.org/downloads/windows/</p>
  <p>Look for the most recent version of <strong>Python 3.11</strong> or <strong>Python 3.12</strong>.
  Click the link that says <strong>"Windows installer (64-bit)"</strong>.</p>
</div>

<h2>Install Python — Step by Step</h2>

<div class="num-step">
  <div class="num">1</div>
  <div class="num-content">
    Find the file you just downloaded. It will be in your <strong>Downloads</strong> folder.
    Its name will look like <code>python-3.12.x-amd64.exe</code>.
    Double-click it to start the installer.
  </div>
</div>
<div class="num-step">
  <div class="num">2</div>
  <div class="num-content">
    <strong>Very important:</strong> At the bottom of the first screen, check the box that says
    <strong>"Add python.exe to PATH"</strong>. This step is critical — if you skip it, nothing will work.
    <br><br>
    <div class="warning-box" style="margin:0">
      <div class="box-title">⚠️ Check This Box Before Clicking Install!</div>
      "Add python.exe to PATH" is at the <em>bottom</em> of the installer window.
      It is easy to miss. If you forget, uninstall Python and start over.
    </div>
  </div>
</div>
<div class="num-step">
  <div class="num">3</div>
  <div class="num-content">
    Click <strong>"Install Now"</strong> (the big blue button at the top).
    Windows may ask permission — click <strong>Yes</strong>.
  </div>
</div>
<div class="num-step">
  <div class="num">4</div>
  <div class="num-content">
    Wait for the installation to finish. It usually takes 1–3 minutes.
    When done, you will see a screen that says <strong>"Setup was successful."</strong>
    Click <strong>Close</strong>.
  </div>
</div>
<div class="num-step">
  <div class="num">5</div>
  <div class="num-content">
    <strong>Verify the installation:</strong> Press the <strong>Windows key</strong> on your keyboard,
    type <code>cmd</code>, and press <strong>Enter</strong>. A black window called
    <strong>Command Prompt</strong> will open.
    Type the following and press Enter:
    <pre><code>python --version</code></pre>
    You should see something like <code>Python 3.12.3</code>.
    If you see that, Python is installed correctly! Close this window.
  </div>
</div>

<div class="tip-box">
  <div class="box-title">💡 What Is Command Prompt?</div>
  Command Prompt is a special window where you type instructions to the computer.
  Instead of clicking buttons, you type commands. It looks like a black screen with white text.
  You will use it a few times to set up and manage this app.
</div>

<!-- ======================================================== SECTION 4 -->
<div class="page-break"></div>
<div class="section-label">Section 4</div>
<h1 id="s4">Step 2 — Get the App Files</h1>

<h2>Where to Put the Files</h2>
<p>
  Save the app folder to this location on your computer:
</p>
<pre><code>C:\\DonutIntel</code></pre>
<p>
  This means the app files will be at <code>C:\\DonutIntel\\</code>.
  Your app window, Command Prompt, and all the instructions in this guide assume the files are here.
  If you put them somewhere else, you will need to adjust the folder paths shown in this guide.
</p>

<h2>Copy the Files</h2>

<div class="num-step">
  <div class="num">1</div>
  <div class="num-content">
    You have received a ZIP file called <code>DonutIntel-Windows.zip</code>.
    Find it in your <strong>Downloads</strong> folder (or wherever it was sent to you).
  </div>
</div>
<div class="num-step">
  <div class="num">2</div>
  <div class="num-content">
    Right-click the ZIP file and choose <strong>"Extract All…"</strong>
  </div>
</div>
<div class="num-step">
  <div class="num">3</div>
  <div class="num-content">
    In the window that appears, type <code>C:\\</code> as the destination and click <strong>Extract</strong>.
    This will create the folder <code>C:\\DonutIntel\\</code> with all the app files inside.
  </div>
</div>
<div class="num-step">
  <div class="num">4</div>
  <div class="num-content">
    Open <strong>File Explorer</strong> (the folder icon in your taskbar) and navigate to
    <code>C:\\DonutIntel</code>. You should see a list of files including
    <code>start.py</code>, <code>stop.py</code>, <code>setup_env.py</code>, and folders
    like <code>backend</code> and <code>frontend</code>.
    If you see these files, you're ready for the next step!
  </div>
</div>

<div class="info-box">
  <div class="box-title">📁 What's Inside the App Folder?</div>
  <table style="margin:8px 0 0;">
    <tr><th>File / Folder</th><th>What It Is</th></tr>
    <tr><td><code>start.py</code></td><td>Start the app server</td></tr>
    <tr><td><code>stop.py</code></td><td>Stop the app server</td></tr>
    <tr><td><code>setup_env.py</code></td><td>First-time setup script</td></tr>
    <tr><td><code>generate_certs.py</code></td><td>Creates security certificates</td></tr>
    <tr><td><code>cli.py</code></td><td>Command line tools</td></tr>
    <tr><td><code>requirements.txt</code></td><td>List of extra software the app needs</td></tr>
    <tr><td><code>backend\\</code></td><td>The "brain" of the app (don't edit these files)</td></tr>
    <tr><td><code>frontend\\</code></td><td>The visual parts of the app (the website pages)</td></tr>
    <tr><td><code>config\\settings.yaml</code></td><td>Your settings and API keys</td></tr>
    <tr><td><code>data\\</code></td><td>Where your product database is stored</td></tr>
    <tr><td><code>logs\\</code></td><td>Activity records (like a diary of what the app did)</td></tr>
    <tr><td><code>exports\\</code></td><td>Where exported spreadsheet files are saved</td></tr>
    <tr><td><code>certs\\</code></td><td>Security certificates for the HTTPS connection</td></tr>
  </table>
</div>

<!-- ======================================================== SECTION 5 -->
<div class="page-break"></div>
<div class="section-label">Section 5</div>
<h1 id="s5">Step 3 — Run First-Time Setup</h1>

<p>
  The setup script does four things automatically:
</p>
<ol>
  <li>Creates a private Python <strong>environment</strong> (a separate space for the app's software)</li>
  <li>Downloads and installs all the extra software the app needs</li>
  <li>Downloads the <strong>Chromium</strong> and <strong>Firefox</strong> browser engines (used for web scraping)</li>
  <li>Creates the security <strong>certificates</strong> so the app can use a secure HTTPS connection</li>
</ol>

<h2>Open Command Prompt and Go to the App Folder</h2>

<div class="num-step">
  <div class="num">1</div>
  <div class="num-content">
    Press the <strong>Windows key</strong>, type <code>cmd</code>, and press <strong>Enter</strong>.
    Command Prompt opens — a black window with a blinking cursor.
  </div>
</div>
<div class="num-step">
  <div class="num">2</div>
  <div class="num-content">
    Type the following command and press <strong>Enter</strong>:
    <pre><code>cd C:\\DonutIntel</code></pre>
    The line at the bottom of the window will now say <code>C:\\DonutIntel&gt;</code>.
    This means you are "inside" the app folder.
  </div>
</div>

<h2>Run the Setup Script</h2>

<div class="num-step">
  <div class="num">3</div>
  <div class="num-content">
    Type the following and press <strong>Enter</strong>:
    <pre><code>python setup_env.py</code></pre>
  </div>
</div>
<div class="num-step">
  <div class="num">4</div>
  <div class="num-content">
    The setup script will start. You will see messages scrolling by.
    <strong>This will take 5–15 minutes</strong> — it is downloading files from the internet.
    Do not close the window. Just wait until you see:
    <pre><code>Setup complete!
  Start:  python start.py
  Stop:   python stop.py</code></pre>
  </div>
</div>

<div class="tip-box">
  <div class="box-title">💡 Something Went Wrong?</div>
  If you see a red error message that says <strong>"python is not recognized"</strong>,
  Python was not installed correctly — specifically, the "Add Python to PATH" box was not checked.
  Uninstall Python from <strong>Control Panel → Programs</strong> and reinstall it,
  making sure to check that box.
</div>

<div class="tip-box">
  <div class="box-title">💡 Setup Already Run?</div>
  If you run <code>setup_env.py</code> again later, it will skip steps that are already done.
  It is safe to run multiple times.
</div>

<!-- ======================================================== SECTION 6 -->
<div class="page-break"></div>
<div class="section-label">Section 6</div>
<h1 id="s6">Step 4 — Configure Your Settings</h1>

<p>
  Before you start the app for the first time, you need to open the settings file and make a few changes.
  The settings file is a plain text file called <code>settings.yaml</code>.
  It controls everything about how the app behaves — your login password, your website addresses, and more.
</p>

<h2>Open the Settings File</h2>

<div class="num-step">
  <div class="num">1</div>
  <div class="num-content">
    Open <strong>File Explorer</strong> and navigate to <code>C:\\DonutIntel\\config\\</code>.
  </div>
</div>
<div class="num-step">
  <div class="num">2</div>
  <div class="num-content">
    Right-click the file <code>settings.yaml</code> and choose <strong>"Open with"</strong>,
    then select <strong>Notepad</strong> (or any text editor you have).
  </div>
</div>

<div class="tip-box">
  <div class="box-title">💡 Better Text Editors (Optional)</div>
  Notepad works fine, but if you want colored text that makes the file easier to read,
  you can download one of these free programs:
  <ul>
    <li><strong>Notepad++:</strong> <span class="url">https://notepad-plus-plus.org/downloads/</span></li>
    <li><strong>VS Code:</strong> <span class="url">https://code.visualstudio.com/</span></li>
  </ul>
</div>

<h2>Required Changes</h2>

<div class="warning-box">
  <div class="box-title">⚠️ Do These Changes Before Starting the App</div>
  The settings below use example placeholder values. You must replace them with your own.
</div>

<h3>Change Your Login Password</h3>
<p>Find this section in the file:</p>
<pre><code>auth:
  enabled: true
  username: admin
  password: changeme</code></pre>
<p>Change <code>changeme</code> to a password only you know. Example:</p>
<pre><code>auth:
  enabled: true
  username: admin
  password: MySecretPassword123!</code></pre>

<h3>Change the Secret Key</h3>
<p>Find this line:</p>
<pre><code>  secret_key: CHANGE_ME_REPLACE_WITH_RANDOM_32_CHARACTER_STRING</code></pre>
<p>
  Replace the value with any random string of letters and numbers that is at least 32 characters long.
  You can make one up — just a random mix of letters and numbers.
  Example (do not use this exact one):
</p>
<pre><code>  secret_key: xK9mP2qL7nR4vT1wY8sA5jB3hC6dE0fZ</code></pre>

<h3>Set the Browser Profile for Windows</h3>
<p>Find this section:</p>
<pre><code>browser:
  default_profile: safari_mac</code></pre>
<p>Change it to:</p>
<pre><code>browser:
  default_profile: chrome_windows</code></pre>

<h2>Optional Settings</h2>

<h3>Add Your Source Websites</h3>
<p>
  The <code>source_sites</code> section lists the websites the app will scrape for products.
  Each entry has fields like <code>domain</code>, <code>base_url</code>, and Shopify credentials.
  If you have a Shopify store, fill in your API key and access token here.
  You can change these settings in the app's Settings screen too (see Section 10).
</p>

<h3>Add API Keys (Optional)</h3>
<p>
  If you have a <strong>SerpAPI</strong> key (for Google Shopping searches),
  find this section and add it:
</p>
<pre><code>serpapi:
  api_key: YOUR_SERPAPI_KEY_HERE</code></pre>
<p>
  If you have an <strong>Anthropic</strong> API key (for AI-powered product categorization),
  find this section:
</p>
<pre><code>anthropic:
  api_key: YOUR_ANTHROPIC_KEY_HERE
  enabled: false</code></pre>
<p>Change <code>enabled: false</code> to <code>enabled: true</code> to turn on AI features.</p>

<h2>Save the File</h2>
<p>
  After making your changes, press <strong>Ctrl+S</strong> to save.
  Close the text editor.
</p>

<div class="warning-box">
  <div class="box-title">⚠️ Keep This File Private</div>
  The <code>settings.yaml</code> file contains your passwords and API keys.
  Do not email it or share it with anyone. Do not upload it to the internet.
</div>

<!-- ======================================================== SECTION 7 -->
<div class="page-break"></div>
<div class="section-label">Section 7</div>
<h1 id="s7">Step 5 — Start the App</h1>

<p>
  Starting the app means turning on the <strong>server</strong> — the program that runs in the background
  and serves the web dashboard to your browser.
  Think of it like turning on a TV before you can watch it.
</p>

<h2>How to Start</h2>

<div class="num-step">
  <div class="num">1</div>
  <div class="num-content">
    Open <strong>Command Prompt</strong>
    (press Windows key, type <code>cmd</code>, press Enter).
  </div>
</div>
<div class="num-step">
  <div class="num">2</div>
  <div class="num-content">
    Navigate to the app folder:
    <pre><code>cd C:\\DonutIntel</code></pre>
  </div>
</div>
<div class="num-step">
  <div class="num">3</div>
  <div class="num-content">
    Start the app:
    <pre><code>python start.py</code></pre>
  </div>
</div>
<div class="num-step">
  <div class="num">4</div>
  <div class="num-content">
    You will see a message like this:
    <pre><code>Starting Donut Intel Platform on https://localhost:8743
  API docs: https://localhost:8743/api/docs
  Press Ctrl+C to stop</code></pre>
    The app is now running! <strong>Leave this window open</strong> — closing it will stop the app.
  </div>
</div>

<div class="tip-box">
  <div class="box-title">💡 Keep the Window Open</div>
  The Command Prompt window <em>must stay open</em> while you use the app.
  You can minimize it (click the minus button), but do not close it.
  Open a <em>separate</em> Command Prompt window if you need to type more commands.
</div>

<!-- ======================================================== SECTION 8 -->
<div class="section-label" style="margin-top:30px">Section 8</div>
<h1 id="s8">Step 6 — Open the App in Your Browser</h1>

<h2>Go to the App Website</h2>

<div class="num-step">
  <div class="num">1</div>
  <div class="num-content">
    Open your web browser (Chrome, Firefox, or Edge).
  </div>
</div>
<div class="num-step">
  <div class="num">2</div>
  <div class="num-content">
    In the address bar at the top, type the following address exactly and press Enter:
    <pre><code>https://localhost:8743</code></pre>
  </div>
</div>

<h2>Accept the Security Notice</h2>
<p>
  Because the app uses a <strong>self-signed certificate</strong> (a security certificate you created yourself),
  your browser will show a warning. <strong>This is normal and safe.</strong>
  The app is only running on your own computer — it is not on the public internet.
</p>

<h3>In Google Chrome:</h3>
<ol>
  <li>You will see a page that says <strong>"Your connection is not private"</strong></li>
  <li>Click <strong>"Advanced"</strong> (at the bottom of the page)</li>
  <li>Click <strong>"Proceed to localhost (unsafe)"</strong></li>
</ol>

<h3>In Microsoft Edge:</h3>
<ol>
  <li>You will see a page that says <strong>"Your connection isn't private"</strong></li>
  <li>Click <strong>"Advanced"</strong></li>
  <li>Click <strong>"Continue to localhost (unsafe)"</strong></li>
</ol>

<h3>In Mozilla Firefox:</h3>
<ol>
  <li>You will see a page that says <strong>"Warning: Potential Security Risk Ahead"</strong></li>
  <li>Click <strong>"Advanced…"</strong></li>
  <li>Click <strong>"Accept the Risk and Continue"</strong></li>
</ol>

<div class="tip-box">
  <div class="box-title">💡 Only Needed Once Per Browser</div>
  After you accept the warning once, your browser remembers and will not ask again
  (until you clear your browser data or switch computers).
</div>

<h2>Log In</h2>

<div class="num-step">
  <div class="num">1</div>
  <div class="num-content">
    You will see a login page. Enter your username and password.
    (Default: <code>admin</code> / the password you set in Step 4.)
  </div>
</div>
<div class="num-step">
  <div class="num">2</div>
  <div class="num-content">
    Click <strong>Sign In</strong>. The dashboard will load and you're in!
  </div>
</div>

<!-- ======================================================== SECTION 9 -->
<div class="page-break"></div>
<div class="section-label">Section 9</div>
<h1 id="s9">Step 7 — Stop the App</h1>

<h2>Method 1 — The Proper Way (Recommended)</h2>
<p>Open a <strong>new</strong> Command Prompt window (don't close the one running the app yet),
navigate to the app folder, and type:</p>
<pre><code>cd C:\\DonutIntel
python stop.py</code></pre>
<p>You will see: <code>Stopped 1 process(es).</code></p>

<h2>Method 2 — Quick Stop</h2>
<p>
  Click on the Command Prompt window where the app is running, then press
  <strong>Ctrl+C</strong> on your keyboard. The app will stop gracefully.
</p>

<div class="warning-box">
  <div class="box-title">⚠️ Always Stop Before Turning Off Your Computer</div>
  Stop the app before shutting down or restarting Windows.
  The database is safe — it uses a technology called WAL mode that protects your data —
  but it is good practice to stop the app cleanly.
</div>

<!-- ======================================================== SECTION 10 -->
<div class="page-break"></div>
<div class="section-label">Section 10</div>
<h1 id="s10">All Features Explained — The Dashboard</h1>

<p>
  The dashboard is the main screen of the app. It is a website that opens in your browser.
  On the left side is a <strong>sidebar</strong> — a list of buttons that take you to different sections.
  Here is what each section does and how to use it.
</p>

<!-- DASHBOARD -->
<div class="feature avoid-break">
  <div class="feature-name">📊 Dashboard — The Home Screen</div>
  <div class="feature-tagline">See everything at a glance</div>
  <p>
    The Dashboard is the first page you see when you log in.
    It shows you a quick summary of everything: how many products you have,
    when the app last ran a scan, and any recent activity.
    There is also a <strong>live log viewer</strong> at the bottom — a scrolling window that shows you
    exactly what the app is doing right now, in real time.
  </p>
  <h4>What You'll See:</h4>
  <ul>
    <li><strong>Stats cards</strong> — Total products, source listings, pending duplicates, new products found recently</li>
    <li><strong>Products by site</strong> — How many products come from each of your websites</li>
    <li><strong>Last scan status</strong> — When did the app last check your websites for new products?</li>
    <li><strong>Live log</strong> — A running record of what the app is currently doing (you can filter by Info, Warning, or Critical messages)</li>
  </ul>
</div>

<!-- PRODUCTS -->
<div class="feature avoid-break">
  <div class="feature-name">📦 Products — Your Product Catalog</div>
  <div class="feature-tagline">Browse and search everything you sell</div>
  <p>
    This is your complete list of products — like a giant shopping catalog for your business.
    Every product the app has found on your websites appears here.
    You can search, filter, sort, and click on any product to see its full details.
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Products</strong> in the left sidebar.</li>
    <li>Use the search box to find a specific product by name.</li>
    <li>Use the filters (dropdowns at the top) to narrow by category, manufacturer, or price range.</li>
    <li>Click any product to open its detail page, where you can see its full price history and competitor matches.</li>
    <li>To search for competitors for multiple products at once: check the boxes next to the products you want, then click <strong>"Search Competitors"</strong>.</li>
  </ol>
</div>

<!-- COMPETITORS -->
<div class="feature avoid-break">
  <div class="feature-name">🏪 Competitors — Track Other Stores</div>
  <div class="feature-tagline">Keep an eye on who's selling what you sell</div>
  <p>
    This section keeps a list of all the competitor websites the app is watching.
    You can add new competitors, see how many of their products match yours,
    and check when the app last looked at their website.
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Competitors</strong> in the left sidebar.</li>
    <li>To add a new competitor: type the website address (domain) in the search box and click <strong>"Add Competitor"</strong>.</li>
    <li>To import many competitors at once: click <strong>"Bulk Import"</strong> and upload a text file with one domain per line.</li>
    <li>To scan a competitor: click the <strong>Scan</strong> button next to their name.</li>
    <li>Click a competitor's name to see all the products the app found on their site.</li>
  </ol>
</div>

<!-- PRICE COMPARISON -->
<div class="feature avoid-break">
  <div class="feature-name">💰 Price Comparison — See Who's Cheaper</div>
  <div class="feature-tagline">Your prices vs. your competitors' prices, side by side</div>
  <p>
    This is one of the most powerful features. It shows a table with your products on the left
    and your competitors' prices on the right. At a glance, you can see which competitors
    are selling the same product for less — and by how much.
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Price Comparison</strong> in the left sidebar.</li>
    <li>Use the filters to search for a specific product or category.</li>
    <li>Prices highlighted in <strong>red</strong> or shown as lower mean a competitor is cheaper than you.</li>
    <li>Click any price to see the source URL and visit that competitor's page.</li>
  </ol>
</div>

<!-- SCANS -->
<div class="feature avoid-break">
  <div class="feature-name">🔍 Scans — View Scan History</div>
  <div class="feature-tagline">See what the app has done and what it found</div>
  <p>
    Every time the app visits a website and collects product information, that is called a <strong>scan</strong>.
    The Scans section shows you a history of every scan: when it ran, how long it took,
    how many products it found, and whether it succeeded or failed.
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Scans</strong> in the left sidebar.</li>
    <li>You will see a list of recent scans with their status (Completed, Running, or Failed).</li>
    <li>Click a scan to see the details — which products were found or updated.</li>
    <li>If a scan is still running, you will see a <strong>Cancel</strong> button next to it.</li>
  </ol>
</div>

<!-- DUPLICATES -->
<div class="feature avoid-break">
  <div class="feature-name">🔁 Duplicates — Clean Up Double Listings</div>
  <div class="feature-tagline">Find and remove products listed more than once</div>
  <p>
    When the app scrapes multiple websites, it sometimes finds the same product listed in more than one place.
    The Duplicates section shows you these suspected matches and lets you decide what to do —
    <strong>merge</strong> them into one record, or <strong>reject</strong> the match if they are actually different products.
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Duplicates</strong> in the left sidebar.</li>
    <li>Each row shows two products that look similar, with a <strong>match score</strong> (0–100%). Higher scores mean they are more likely to be the same product.</li>
    <li>Click <strong>Merge</strong> to combine them into one product.</li>
    <li>Click <strong>Reject</strong> if they are different products and you do not want to merge them.</li>
    <li>You can also run the automatic deduplication by going to <strong>Dashboard → Run Dedup</strong>.</li>
  </ol>
</div>

<!-- SOURCE PRODUCTS -->
<div class="feature avoid-break">
  <div class="feature-name">📂 Source Products — Browse by Website</div>
  <div class="feature-tagline">See raw product data from each individual source site</div>
  <p>
    While the Products section shows all products merged together,
    Source Products lets you look at the raw data from each specific website separately.
    This is useful for checking what the app found on a particular website.
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Source Products</strong> in the left sidebar.</li>
    <li>Choose which website you want to browse from the dropdown at the top.</li>
    <li>You will see all the products the app found on that website, with their prices and details.</li>
  </ol>
</div>

<!-- STORE COMPARE -->
<div class="feature avoid-break">
  <div class="feature-name">🔀 Store Compare — Products Across Your Sites</div>
  <div class="feature-tagline">Are the same products on all your stores?</div>
  <p>
    If you have products on multiple websites, Store Compare helps you find any
    products that are missing from one site but present on another,
    and shows you where the same product has different prices across your stores.
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Store Compare</strong> in the left sidebar.</li>
    <li>Select two sites to compare from the dropdowns.</li>
    <li>The app will show you products that exist on one site but not the other,
    and flag products where the prices are different.</li>
  </ol>
</div>

<!-- SHOPIFY SYNC -->
<div class="feature avoid-break">
  <div class="feature-name">🛍️ Shopify Sync — Send Products to Shopify</div>
  <div class="feature-tagline">Push your product catalog to a Shopify store</div>
  <p>
    If you use <strong>Shopify</strong> (an online store platform), this feature lets you
    export your product data directly to your Shopify store.
    You choose which products to send, how to handle conflicts,
    and the app will update your Shopify store automatically.
    <em>You need a Shopify API key configured in settings to use this feature.</em>
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Shopify Sync</strong> in the left sidebar.</li>
    <li>Choose a source site from the dropdown.</li>
    <li>Configure how to handle existing products (merge, replace, or skip).</li>
    <li>Click <strong>Preview</strong> to see what changes will be made.</li>
    <li>Click <strong>Execute Sync</strong> to send the data to Shopify.</li>
  </ol>
</div>

<!-- LIVE SYNC -->
<div class="feature avoid-break">
  <div class="feature-name">⚡ Live Sync — Real-Time Shopify Updates</div>
  <div class="feature-tagline">Keep your Shopify store in sync automatically</div>
  <p>
    Similar to Shopify Sync but uses Shopify's live API connection for real-time updates.
    This is the more powerful version that lets you map specific fields
    (title, price, images, inventory) between your data and your Shopify store.
    Changes are shown with a risk level (Low, Medium, High) before you confirm.
    <em>Requires Shopify API credentials in settings.</em>
  </p>
</div>

<!-- FIND PRODUCT -->
<div class="feature avoid-break">
  <div class="feature-name">🔎 Find Product — Search Your Catalog</div>
  <div class="feature-tagline">Quickly look up any product in your catalog</div>
  <p>
    A fast search tool for finding a specific product in your catalog.
    Type a description, model number, or keywords and the app will find the closest matches.
    The results show a <strong>match score</strong> so you know how closely each result matches your search.
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Find Product</strong> in the left sidebar.</li>
    <li>Type what you're looking for in the search box.</li>
    <li>Adjust the <strong>minimum match score</strong> slider if you're getting too many or too few results.</li>
    <li>Your past searches are saved in a history list at the bottom.</li>
  </ol>
</div>

<!-- BEAT THIS PRICE -->
<div class="feature avoid-break">
  <div class="feature-name">💡 Beat This Price — Find a Cheaper Source</div>
  <div class="feature-tagline">Can you buy something cheaper from a competitor?</div>
  <p>
    You describe a product and give a target price.
    The app searches the internet to find if any competitors are selling that product below your price.
    Great for checking if you can find a better deal on something you need to buy or sell.
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Beat This Price</strong> in the left sidebar.</li>
    <li>Type a product description and the price you want to beat.</li>
    <li>Optionally add details like manufacturer, size, or color to narrow down the search.</li>
    <li>Click <strong>Search</strong> and wait for results.</li>
    <li>Results show competitor stores and their prices for that product.</li>
  </ol>
</div>

<!-- FIND CUSTOMERS -->
<div class="feature avoid-break">
  <div class="feature-name">👥 Find Customers — Discover New Business Leads</div>
  <div class="feature-tagline">Find businesses that might want to buy what you sell</div>
  <p>
    This feature searches the internet for businesses in a specific area that might be
    good customers for your products.
    You give it a business type, a city or region, and it finds matching businesses.
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Find Customers</strong> in the left sidebar.</li>
    <li>Enter the type of business you are looking for (e.g., "bakery" or "café").</li>
    <li>Enter a location (city, state, or zip code).</li>
    <li>Optionally enter website addresses or company names to exclude from results.</li>
    <li>Click <strong>Search</strong> to get a list of matching businesses.</li>
  </ol>
</div>

<!-- SOURCE SYNC -->
<div class="feature avoid-break">
  <div class="feature-name">🔄 Source Sync — Sync Products Between Your Sites</div>
  <div class="feature-tagline">Make sure all your sites have the same products</div>
  <p>
    If you run several websites (such as a wholesale site and a retail site),
    Source Sync helps you keep them all consistent.
    It compares your sites to find missing products or pricing mismatches
    and lets you approve changes to sync them up.
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Source Sync</strong> in the left sidebar.</li>
    <li>Choose which sites to compare.</li>
    <li>Review the differences — missing products are shown in one list, price differences in another.</li>
    <li>Click <strong>Approve</strong> on each change you want to make, or <strong>Reject</strong> to skip it.</li>
    <li>Click <strong>Run Cycle</strong> to apply all approved changes.</li>
  </ol>
</div>

<!-- SYSTEM OF RECORD -->
<div class="feature avoid-break">
  <div class="feature-name">🏛️ System of Record — Set Your Primary Data Source</div>
  <div class="feature-tagline">Which site is the "true" version of your product data?</div>
  <p>
    When you have products on multiple sites, one of them needs to be the <strong>master</strong> —
    the one you trust most.
    System of Record lets you pick that primary site and then compare all other sites against it.
    It has four tabs: Missing, Differing, Matching, and Fuzzy (close but not exact matches).
  </p>
</div>

<!-- SCHEDULER -->
<div class="feature avoid-break">
  <div class="feature-name">⏰ Scheduler — Automate Tasks</div>
  <div class="feature-tagline">Set the app to run scans automatically on a schedule</div>
  <p>
    Instead of manually starting scans every day, you can set up a schedule.
    For example: "Scan all source sites every morning at 9 AM" or
    "Check competitor prices every Monday at 7 AM."
    The app handles the rest automatically, even if you are not at your computer.
  </p>
  <h4>How to Create a Scheduled Job:</h4>
  <ol>
    <li>Click <strong>Scheduler</strong> in the left sidebar.</li>
    <li>Click <strong>"New Job"</strong>.</li>
    <li>Give it a name, choose a job type (e.g., Source Scan, Competitor Scan, Export).</li>
    <li>Choose when to run it: Daily, Weekly, Monthly, or a custom schedule (cron).</li>
    <li>Click <strong>Save</strong>. The job will now run automatically at the time you set.</li>
    <li>You can also click <strong>"Run Now"</strong> next to any job to run it immediately.</li>
  </ol>
</div>

<!-- REPORTS -->
<div class="feature avoid-break">
  <div class="feature-name">📋 Reports — Generate Summary Documents</div>
  <div class="feature-tagline">Create printable reports about your catalog and pricing</div>
  <p>
    The Reports section lets you generate HTML reports you can read or save.
    There are four types:
  </p>
  <ul>
    <li><strong>Summary</strong> — Overview of your catalog over the last N days</li>
    <li><strong>Price Disparity</strong> — Products where competitor prices differ by more than a certain percentage</li>
    <li><strong>Competitor Profile</strong> — Everything the app knows about one specific competitor</li>
    <li><strong>Price Comparison</strong> — Full price history for one specific product</li>
  </ul>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Reports</strong> in the left sidebar.</li>
    <li>Choose a report type from the dropdown.</li>
    <li>Fill in any required details (competitor ID, number of days, etc.).</li>
    <li>Click <strong>Generate</strong>. The report opens in the same window.</li>
    <li>Click <strong>Download</strong> to save the report as an HTML file.</li>
  </ol>
</div>

<!-- EXPORT -->
<div class="feature avoid-break">
  <div class="feature-name">📤 Export — Download Your Data as a Spreadsheet</div>
  <div class="feature-tagline">Save your product catalog to Excel or CSV</div>
  <p>
    Export lets you download your entire product catalog (or a filtered portion)
    as a spreadsheet file. You can open it in Microsoft Excel or Google Sheets.
    Files are saved to the <code>exports</code> folder inside the app.
  </p>
  <h4>How to Use It:</h4>
  <ol>
    <li>Click <strong>Export</strong> in the left sidebar.</li>
    <li>Choose a format: <strong>CSV</strong> (works in Excel and Google Sheets), <strong>XLSX</strong> (Excel format), or <strong>TXT</strong> (plain text).</li>
    <li>Choose which fields (columns) to include in the export.</li>
    <li>Click <strong>Export</strong>. The file will download to your browser's Downloads folder.</li>
    <li>Past exports are listed at the bottom so you can re-download them.</li>
  </ol>
</div>

<!-- SETTINGS -->
<div class="feature avoid-break">
  <div class="feature-name">⚙️ Settings — Configure the App</div>
  <div class="feature-tagline">Change passwords, API keys, and behavior</div>
  <p>
    The Settings screen lets you change most app configuration directly from the browser —
    no need to edit <code>settings.yaml</code> by hand.
    Changes take effect immediately without restarting the app.
  </p>
  <table>
    <tr><th>Tab</th><th>What You Can Do</th></tr>
    <tr><td><strong>Auth</strong></td><td>Change your login username and password, enable/disable login, set session timeout</td></tr>
    <tr><td><strong>Database</strong></td><td>See where your database is stored, run a backup, change the database path</td></tr>
    <tr><td><strong>Webhook</strong></td><td>Set up a URL that receives notifications when scans finish or prices change</td></tr>
    <tr><td><strong>Shopify</strong></td><td>Add or change API keys for each Shopify store</td></tr>
    <tr><td><strong>Logging</strong></td><td>Choose how detailed the log should be (INFO = normal, DEBUG = very detailed)</td></tr>
    <tr><td><strong>Scraping</strong></td><td>Control how fast/slow the app scrapes (delays, timeouts, retries)</td></tr>
    <tr><td><strong>AI (Anthropic)</strong></td><td>Enter your Anthropic API key and enable AI product categorization</td></tr>
    <tr><td><strong>Managed Lists</strong></td><td>Add domains to exclude from competitor results, add known manufacturer URLs</td></tr>
  </table>
</div>

<!-- ======================================================== SECTION 11 -->
<div class="page-break"></div>
<div class="section-label">Section 11</div>
<h1 id="s11">Command Line Tools (Advanced)</h1>

<p>
  The <strong>Command Line</strong> is a way to run tasks by typing commands instead of clicking buttons.
  You don't need to use these for everyday tasks — the web dashboard handles most things.
  But these commands are useful for automating tasks, running bulk operations, or doing things quickly.
</p>

<div class="info-box">
  <div class="box-title">📌 How to Run a Command</div>
  <ol style="margin:6px 0 0 20px;">
    <li>Open Command Prompt (Windows key → type <code>cmd</code> → Enter)</li>
    <li>Type: <code>cd C:\\DonutIntel</code> and press Enter</li>
    <li>Type the command shown below and press Enter</li>
  </ol>
  <p style="margin-top:8px;">All commands start with <code>python cli.py</code> followed by the command name.</p>
</div>

<h2>Available Commands</h2>

<div class="avoid-break">
<h3>scan — Scrape Your Source Websites</h3>
<p>Visits your source websites and collects all their products and prices.</p>
<pre><code>python cli.py scan</code></pre>
<p>To scan just one specific website:</p>
<pre><code>python cli.py scan --site donut-supplies.com</code></pre>
</div>

<div class="avoid-break">
<h3>competitor-scan — Scan Competitor Websites</h3>
<p>Visits competitor websites in your database and collects their products and prices.</p>
<pre><code>python cli.py competitor-scan</code></pre>
<p>To scan one specific competitor:</p>
<pre><code>python cli.py competitor-scan --domain example.com</code></pre>
</div>

<div class="avoid-break">
<h3>yahoo-scan — Search Yahoo Shopping for Prices</h3>
<p>Searches Yahoo Shopping (product listing ads) for competitor prices for your products.</p>
<pre><code>python cli.py yahoo-scan</code></pre>
<p>To search for a specific product by ID:</p>
<pre><code>python cli.py yahoo-scan --product-id 42</code></pre>
<p>To search using a custom search phrase:</p>
<pre><code>python cli.py yahoo-scan --query "commercial donut fryer"</code></pre>
</div>

<div class="avoid-break">
<h3>import-competitors — Add Competitor Domains</h3>
<p>Import a list of competitor websites all at once.</p>
<p>To import from a text file (one domain per line):</p>
<pre><code>python cli.py import-competitors --file C:\\competitors.txt</code></pre>
<p>To add a few domains directly on the command line:</p>
<pre><code>python cli.py import-competitors --domains competitor1.com competitor2.com</code></pre>
</div>

<div class="avoid-break">
<h3>dedup — Find and Merge Duplicate Products</h3>
<p>Runs the automatic duplicate-detection engine. It will find products that look like duplicates
and either merge them automatically (high confidence) or flag them for your review (lower confidence).</p>
<pre><code>python cli.py dedup</code></pre>
</div>

<div class="avoid-break">
<h3>stats — Show App Statistics</h3>
<p>Prints a summary of what's in your database: number of products, competitors, scans, and more.</p>
<pre><code>python cli.py stats</code></pre>
</div>

<div class="avoid-break">
<h3>export — Export Product Data to a File</h3>
<p>Saves your product catalog to a spreadsheet or text file.</p>
<pre><code>python cli.py export --format csv</code></pre>
<p>To export as Excel format:</p>
<pre><code>python cli.py export --format xlsx</code></pre>
<p>To save to a specific file:</p>
<pre><code>python cli.py export --format csv --output C:\\Users\\YourName\\Desktop\\products.csv</code></pre>
</div>

<div class="avoid-break">
<h3>report — Generate a Report</h3>
<p>Creates an HTML report you can open in your browser.</p>
<pre><code>python cli.py report --type summary</code></pre>
<p>Available report types:</p>
<table>
  <tr><th>Command</th><th>What It Generates</th></tr>
  <tr><td><code>--type summary</code></td><td>Overview of catalog activity (last 7 days by default)</td></tr>
  <tr><td><code>--type summary --days 30</code></td><td>Overview for the last 30 days</td></tr>
  <tr><td><code>--type disparity --threshold 5</code></td><td>Products where a competitor is more than 5% cheaper</td></tr>
  <tr><td><code>--type competitor --id 12</code></td><td>Full profile of competitor #12</td></tr>
  <tr><td><code>--type price --id 42</code></td><td>Full price history for product #42</td></tr>
</table>
</div>

<div class="avoid-break">
<h3>dbpath — View or Change the Database Location</h3>
<p>Shows where your database file is saved.</p>
<pre><code>python cli.py dbpath</code></pre>
<p>To move it to a new location (takes effect after restart):</p>
<pre><code>python cli.py dbpath --set C:\\Users\\YourName\\Documents\\donut_intel.db</code></pre>
</div>

<div class="avoid-break">
<h3>schedule — Manage Scheduled Jobs</h3>
<p>List, create, run, and delete automatic scheduled tasks.</p>
<p>See all scheduled jobs:</p>
<pre><code>python cli.py schedule list</code></pre>
<p>Create a daily scan at 9:00 AM:</p>
<pre><code>python cli.py schedule create --name "Daily Scan" --job-type source_scan --schedule-type daily --schedule-value "09:00"</code></pre>
<p>Run a job immediately (replace 1 with the job ID from <code>schedule list</code>):</p>
<pre><code>python cli.py schedule run --id 1</code></pre>
<p>Delete a job:</p>
<pre><code>python cli.py schedule delete --id 1</code></pre>
</div>

<!-- ======================================================== SECTION 12 -->
<div class="page-break"></div>
<div class="section-label">Section 12</div>
<h1 id="s12">Automatic Scheduled Tasks</h1>

<p>
  Scheduled tasks let the app run on autopilot. You set them up once and they run automatically —
  no need to remember to do anything each day.
</p>

<div class="warning-box">
  <div class="box-title">⚠️ The App Must Be Running for Scheduled Tasks to Work</div>
  Scheduled tasks only run while the app's server is running (i.e., while <code>start.py</code> is active).
  If the app is stopped, scheduled tasks will not fire.
  Consider keeping the app running at all times on a dedicated machine or server.
</div>

<h2>Types of Scheduled Jobs</h2>

<table>
  <tr><th>Job Type</th><th>What It Does</th></tr>
  <tr><td><code>source_scan</code></td><td>Visits your source websites and collects updated products and prices</td></tr>
  <tr><td><code>competitor_scan</code></td><td>Visits competitor websites and collects their products and prices</td></tr>
  <tr><td><code>export</code></td><td>Automatically exports your catalog to a spreadsheet file</td></tr>
  <tr><td><code>price_check</code></td><td>Checks for price changes and logs any differences</td></tr>
</table>

<h2>Schedule Formats</h2>

<table>
  <tr><th>Type</th><th>Format</th><th>Example</th><th>Meaning</th></tr>
  <tr><td>Daily</td><td><code>HH:MM</code></td><td><code>09:00</code></td><td>Every day at 9:00 AM</td></tr>
  <tr><td>Weekly</td><td><code>day:HH:MM</code></td><td><code>mon:07:30</code></td><td>Every Monday at 7:30 AM</td></tr>
  <tr><td>Monthly</td><td><code>date:HH:MM</code></td><td><code>1:08:00</code></td><td>1st of each month at 8:00 AM</td></tr>
  <tr><td>Interval</td><td>minutes</td><td><code>60</code></td><td>Every 60 minutes</td></tr>
</table>

<h2>Recommended Setup for Most Users</h2>

<div class="step-box">
  <div class="box-title">📅 Suggested Daily Schedule</div>
  <ul>
    <li><strong>6:00 AM</strong> — Source scan (collect your latest products)</li>
    <li><strong>7:00 AM</strong> — Competitor scan (check competitor prices)</li>
    <li><strong>8:00 AM</strong> — Export (save a fresh spreadsheet)</li>
  </ul>
  Set these up once in the Scheduler tab and the app does the rest.
</div>

<!-- ======================================================== SECTION 13 -->
<div class="page-break"></div>
<div class="section-label">Section 13</div>
<h1 id="s13">Troubleshooting</h1>

<p>Here are the most common problems and how to fix them.</p>

<table>
  <tr><th>Problem</th><th>Most Likely Cause</th><th>Solution</th></tr>
  <tr>
    <td><strong>"python is not recognized"</strong> error in Command Prompt</td>
    <td>Python is not installed, or "Add to PATH" was not checked</td>
    <td>Uninstall Python and reinstall it. On the first screen of the installer, check "Add python.exe to PATH" before clicking Install.</td>
  </tr>
  <tr>
    <td>Browser shows "This site can't be reached" at <code>https://localhost:8743</code></td>
    <td>The app is not running</td>
    <td>Open Command Prompt, <code>cd C:\\DonutIntel</code>, and run <code>python start.py</code>. Keep that window open.</td>
  </tr>
  <tr>
    <td>Browser shows a security warning (certificate error)</td>
    <td>Self-signed certificate — expected behavior</td>
    <td>This is normal. Click "Advanced" then "Proceed to localhost (unsafe)." See Section 8 for detailed steps.</td>
  </tr>
  <tr>
    <td><code>setup_env.py</code> fails with "error: Microsoft Visual C++ required"</td>
    <td>A Python package needs C++ build tools</td>
    <td>Download and install "Microsoft C++ Build Tools" from: <span class="url">https://visualstudio.microsoft.com/visual-cpp-build-tools/</span></td>
  </tr>
  <tr>
    <td>Scan runs but finds no products</td>
    <td>Source site URLs are not configured, or the site changed its layout</td>
    <td>Check that <code>source_sites</code> in settings.yaml has the correct domain and base_url for your websites.</td>
  </tr>
  <tr>
    <td>"Address already in use" error when starting</td>
    <td>A previous instance of the app is still running</td>
    <td>Run <code>python stop.py</code> first, then <code>python start.py</code>.</td>
  </tr>
  <tr>
    <td>Login page says "Invalid username or password"</td>
    <td>Wrong password in settings, or settings not saved</td>
    <td>Open <code>config\\settings.yaml</code> and double-check the <code>auth.password</code> value. Make sure you saved the file.</td>
  </tr>
  <tr>
    <td><code>setup_env.py</code> stops at "Installing Playwright browser engines"</td>
    <td>Slow internet connection or firewall blocking downloads</td>
    <td>Wait — this step can take 5–10 minutes on a slow connection. If it fails, run <code>python setup_env.py</code> again to resume.</td>
  </tr>
  <tr>
    <td>Port 8743 is blocked by a firewall or antivirus</td>
    <td>Security software blocking the port</td>
    <td>Add an exception for port 8743 in your Windows Firewall settings, or change the port in <code>config\\settings.yaml</code> under <code>app.port</code>.</td>
  </tr>
</table>

<h2>Getting Help</h2>
<p>
  If you are still stuck, check the log files in the <code>C:\\DonutIntel\\logs\\</code> folder.
  The file <code>donut_intel.log</code> contains a detailed record of what the app did and any errors it encountered.
  You can open it in Notepad.
</p>

<!-- ======================================================== GLOSSARY -->
<div class="page-break"></div>
<div class="section-label">Glossary</div>
<h1 id="glossary">Glossary — Words and What They Mean</h1>

<dl>
  <dt>API / API Key</dt>
  <dd>An <em>API (Application Programming Interface)</em> is a way for two computer programs to talk to each other. An <em>API key</em> is like a password that proves you have permission to use that service. For example, a SerpAPI key lets this app ask Google Shopping for price information.</dd>

  <dt>Browser Engine</dt>
  <dd>A program that can load and understand web pages — like the inside of a web browser without the user interface. Chromium (used by Chrome) and Firefox are examples. The app uses these engines to visit websites and read their content.</dd>

  <dt>Certificate / SSL Certificate</dt>
  <dd>A file that proves a website is secure and creates an encrypted connection. The "S" in "HTTPS" stands for Secure. This app uses a <em>self-signed certificate</em> — one you created yourself — which is why browsers show a warning. It is still secure for local use.</dd>

  <dt>Command Prompt</dt>
  <dd>A black window where you type text commands to control your computer. Also called "CMD" or "Terminal." You use it to start the app, run scans, and more.</dd>

  <dt>Competitor</dt>
  <dd>In this app, a competitor is any website that sells products similar to yours. The app tracks competitor prices so you can compare them to your own.</dd>

  <dt>CSV / XLSX</dt>
  <dd>File formats for spreadsheets. <em>CSV (Comma-Separated Values)</em> is a simple format that works in any spreadsheet program. <em>XLSX</em> is the Microsoft Excel format. Both can be opened in Excel or Google Sheets.</dd>

  <dt>Dashboard</dt>
  <dd>The main screen of a computer program, showing a summary of everything at once — like the dashboard of a car that shows speed, fuel level, and warning lights.</dd>

  <dt>Database</dt>
  <dd>A file that stores information in an organized way so it can be searched and updated quickly. This app uses a database called SQLite to store all your products, prices, and competitor data. Your database file is at <code>data\\donut_intel.db</code>.</dd>

  <dt>Deduplication / Dedup</dt>
  <dd>The process of finding duplicate records (things listed more than once) and merging them into a single record. If the same product was scraped from two different websites, dedup will notice they are the same product and combine them.</dd>

  <dt>Domain</dt>
  <dd>The address of a website, like <code>amazon.com</code> or <code>competitor-store.com</code>. When you add a competitor, you enter their domain.</dd>

  <dt>Export</dt>
  <dd>Saving data from the app to a file on your computer that you can use elsewhere, like a spreadsheet.</dd>

  <dt>HTTPS</dt>
  <dd>A secure version of the web. The "S" stands for Secure. When a website address starts with <code>https://</code>, the connection between your browser and the website is encrypted (scrambled) so no one can spy on it.</dd>

  <dt>localhost</dt>
  <dd>A special address that means "this computer." When you visit <code>https://localhost:8743</code>, your browser is connecting to a web server running on your own machine — not the internet.</dd>

  <dt>Match Score</dt>
  <dd>A number from 0 to 100% that says how similar two things are. A score of 100% means they are identical. A score of 60% means they are probably the same but with some differences. The app uses match scores to identify duplicate products and competitor price matches.</dd>

  <dt>PATH (Environment Variable)</dt>
  <dd>A list of folders that Windows searches when you type a command. When you check "Add Python to PATH" during installation, it tells Windows where to find Python so you can type <code>python</code> in Command Prompt without typing the full path to the program.</dd>

  <dt>Port</dt>
  <dd>Like a door number on a computer. Multiple programs can run at the same time, each listening on a different port number. This app uses port <code>8743</code>, which is why the address ends with <code>:8743</code>.</dd>

  <dt>Python</dt>
  <dd>A popular programming language used to build many kinds of software, including this app. It is free and works on all major operating systems.</dd>

  <dt>Scan / Scraping</dt>
  <dd>When the app visits a website and reads all the product information it finds there. The act of automatically reading a website's content is called <em>web scraping</em>.</dd>

  <dt>Scheduler</dt>
  <dd>A feature that runs tasks automatically at set times — like an alarm clock for the app.</dd>

  <dt>Server</dt>
  <dd>A program that runs in the background and responds to requests. When you type <code>python start.py</code>, you are starting the app's server. Your browser connects to this server to show you the dashboard.</dd>

  <dt>Shopify</dt>
  <dd>A popular e-commerce platform for building online stores. If your store runs on Shopify, this app can connect to it using a Shopify API key to sync product data.</dd>

  <dt>Virtual Environment (.venv)</dt>
  <dd>A private, isolated copy of Python that only this app uses. This prevents conflicts with other Python programs on your computer. The <code>setup_env.py</code> script creates this automatically in the <code>.venv</code> folder.</dd>

  <dt>YAML (.yaml file)</dt>
  <dd>A type of text file used to store settings in a human-readable format. The <code>settings.yaml</code> file uses this format. It is organized with categories and sub-items, like an outline.</dd>
</dl>

<hr>
<p style="text-align:center;color:#888;font-size:12px;margin-top:30px;">
  Donut Intel Platform — Windows Setup &amp; User Guide &nbsp;|&nbsp; Version 2.0<br>
  For support, check the log files at <code>C:\\DonutIntel\\logs\\donut_intel.log</code>
</p>

</body>
</html>
"""

# ---------------------------------------------------------------------------
# Sanitized settings.yaml for the ZIP
# ---------------------------------------------------------------------------

# Any config key whose name contains one of these is treated as a secret and
# scrubbed recursively — so new secret fields (e.g. ai.anthropic_api_key,
# brightdata.api_token) are caught automatically without editing this list.
_SECRET_KEY_HINTS = (
    'password', 'passwd', 'secret', 'token', 'api_key', 'apikey',
    'access_token', 'client_secret',
)


def _is_placeholder(v: str) -> bool:
    """Empty, 'changeme', or an existing YOUR_/CHANGE_ME placeholder — safe to keep."""
    up = v.strip().upper()
    return (not up) or up == 'CHANGEME' or up.startswith('YOUR_') or up.startswith('CHANGE_ME')


def _scrub(obj) -> None:
    """Recursively replace any real-looking secret value with a placeholder."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                _scrub(v)
            elif isinstance(v, str) and any(h in k.lower() for h in _SECRET_KEY_HINTS):
                if not _is_placeholder(v):
                    obj[k] = f'YOUR_{k.upper()}_HERE'
    elif isinstance(obj, list):
        for item in obj:
            _scrub(item)


def _sanitized_config() -> str:
    config_path = ROOT / 'config' / 'settings.yaml'
    cfg = yaml.safe_load(config_path.read_text(encoding='utf-8'))

    # Nice, specific placeholders for the well-known fields...
    cfg['app']['secret_key'] = 'CHANGE_ME_REPLACE_WITH_RANDOM_32_CHARACTER_STRING'
    if isinstance(cfg.get('anthropic'), dict):
        cfg['anthropic']['api_key'] = 'YOUR_ANTHROPIC_API_KEY_HERE'
    if isinstance(cfg.get('serpapi'), dict):
        cfg['serpapi']['api_key'] = 'YOUR_SERPAPI_API_KEY_HERE'
    if isinstance(cfg.get('brightdata'), dict):
        cfg['brightdata']['api_token'] = 'YOUR_BRIGHTDATA_API_TOKEN_HERE'
    for site in cfg.get('source_sites', []):
        site['shopify_api_key'] = 'YOUR_SHOPIFY_API_KEY_HERE'
        site['shopify_access_token'] = 'YOUR_SHOPIFY_ACCESS_TOKEN_HERE'
        site['shopify_client_id'] = 'YOUR_SHOPIFY_CLIENT_ID_HERE'
        site['shopify_client_secret'] = 'YOUR_SHOPIFY_CLIENT_SECRET_HERE'

    # ...then a recursive sweep as a safety net for anything not listed above.
    _scrub(cfg)

    return yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# PDF generation via Playwright
# ---------------------------------------------------------------------------

def generate_pdf() -> Path:
    html_path = ROOT / '_guide_tmp.html'
    pdf_path = ROOT / 'WINDOWS-SETUP-GUIDE.pdf'

    html_path.write_text(HTML, encoding='utf-8')

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(html_path.as_uri())
            page.wait_for_load_state('networkidle')
            page.pdf(
                path=str(pdf_path),
                format='Letter',
                print_background=True,
                margin={'top': '0.75in', 'bottom': '0.75in',
                        'left': '0.85in', 'right': '0.85in'},
            )
            browser.close()
    finally:
        html_path.unlink(missing_ok=True)

    print(f'PDF created: {pdf_path.name}  ({pdf_path.stat().st_size // 1024} KB)')
    return pdf_path


# ---------------------------------------------------------------------------
# ZIP creation
# ---------------------------------------------------------------------------

# Runtime dirs (logs/exports/data/certs) are excluded wholesale and recreated
# empty below — they hold live logs (which can contain secrets), the customer
# database, and the dev TLS private key, none of which should ship.
_EXCLUDE_DIRS  = {
    '.venv', '__pycache__', '.git', '.pytest_cache', '.mypy_cache',
    'node_modules', '.claude', 'logs', 'exports', 'data', 'certs',
}
_EXCLUDE_EXTS  = {'.pyc', '.pyo', '.db', '.db-shm', '.db-wal', '.log', '.enc',
                  '.jsonl', '.out', '.pem', '.key'}
_EXCLUDE_FILES = {
    'create_windows_package.py',
    '_guide_tmp.html',
    'com.donutintel.app.plist',   # macOS LaunchAgent — not needed on Windows
    'setup_macos.sh',              # macOS-only setup
    'uvicorn.out',
}
_EXCLUDE_NAMES_ANY = {'.DS_Store', 'Thumbs.db'}

def _should_exclude(src: Path) -> bool:
    """Return True if this path should be omitted from the ZIP."""
    rel = src.relative_to(ROOT)
    parts = rel.parts
    if any(p in _EXCLUDE_DIRS for p in parts):
        return True
    if src.suffix.lower() in _EXCLUDE_EXTS:
        return True
    if src.name in _EXCLUDE_FILES or src.name in _EXCLUDE_NAMES_ANY:
        return True
    # Catch .bak, .bak-TIMESTAMP, .bak-anything
    if '.bak' in src.name:
        return True
    # Catch rotated logs (donut_intel.log.1, .log.2, …) whose suffix is .1/.2
    if '.log' in src.name:
        return True
    return False


def create_zip(pdf_path: Path) -> Path:
    zip_path = ROOT / 'DonutIntel-Windows.zip'
    sanitized = _sanitized_config()
    inner = 'DonutIntel'   # folder name inside the ZIP → extracts to C:\DonutIntel

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:

        # Walk all project files
        for src in sorted(ROOT.rglob('*')):
            if _should_exclude(src):
                continue
            # Skip the zip file itself and the PDF (added separately below)
            if src == zip_path or src == pdf_path:
                continue

            rel = src.relative_to(ROOT)
            arc = f'{inner}/{rel.as_posix()}'

            if src.is_file():
                if str(rel) == 'config/settings.yaml':
                    zf.writestr(arc, sanitized)
                else:
                    zf.write(src, arc)
            # Directories are created implicitly; add .gitkeep for empty ones
            elif src.is_dir() and not any(src.rglob('*')):
                zf.writestr(f'{arc}/.gitkeep', '')

        # Ensure required empty directories exist in ZIP
        for d in ('data', 'logs', 'exports', 'certs'):
            placeholder = f'{inner}/{d}/.gitkeep'
            names = zf.namelist()
            if not any(n.startswith(f'{inner}/{d}/') for n in names):
                zf.writestr(placeholder, '')

        # Add the PDF guide
        if pdf_path.exists():
            zf.write(pdf_path, f'{inner}/WINDOWS-SETUP-GUIDE.pdf')

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f'ZIP created: {zip_path.name}  ({size_mb:.1f} MB)')
    print(f'\nTo deploy on Windows:')
    print(f'  1. Email or copy DonutIntel-Windows.zip to the Windows machine')
    print(f'  2. Right-click the ZIP → "Extract All…" → destination: C:\\')
    print(f'  3. The app will be at C:\\DonutIntel\\')
    print(f'  4. Follow WINDOWS-SETUP-GUIDE.pdf inside the ZIP')
    return zip_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print('=== Donut Intel — Windows Package Builder ===\n')
    print('[1/2] Generating PDF guide...')
    pdf = generate_pdf()

    print('\n[2/2] Creating ZIP package...')
    create_zip(pdf)

    print('\nDone.')
