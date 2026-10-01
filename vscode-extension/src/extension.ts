import * as vscode from 'vscode';
import * as crypto from 'crypto';
import { ActivityEvent, CollectorClient } from './collector-client';

interface CurrentSession {
    file: string;
    workspace: string;
    language: string;
    startTime: Date;
}

let currentSession: CurrentSession | null = null;
let isWindowFocused = true;
let outputChannel: vscode.OutputChannel;
let collectorClient: CollectorClient;
let statusBarItem: vscode.StatusBarItem;

function getOffsetString(date: Date): string {
    const offset = date.getTimezoneOffset();
    const sign = offset > 0 ? '-' : '+';
    const absOffset = Math.abs(offset);
    const hours = Math.floor(absOffset / 60).toString().padStart(2, '0');
    const minutes = (absOffset % 60).toString().padStart(2, '0');
    return `${sign}${hours}:${minutes}`;
}

function toIso8601WithTimezone(date: Date): string {
    const pad = (n: number) => n.toString().padStart(2, '0');
    const year = date.getFullYear();
    const month = pad(date.getMonth() + 1);
    const day = pad(date.getDate());
    const hours = pad(date.getHours());
    const minutes = pad(date.getMinutes());
    const seconds = pad(date.getSeconds());
    const offset = getOffsetString(date);
    return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}${offset}`;
}

export function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('Activity Tracker');
    collectorClient = new CollectorClient(outputChannel);
    
    outputChannel.appendLine('Activity Tracker Extension Activated');

    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.text = '$(watch) Tracker: Active';
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);

    const showStatusCmd = vscode.commands.registerCommand('activityTracker.showStatus', () => {
        const status = currentSession 
            ? `Tracking ${currentSession.file} in ${currentSession.workspace}`
            : 'Not currently tracking an active editor';
        vscode.window.showInformationMessage(`Activity Tracker: ${status}. Events sent today: ${collectorClient.eventsSentToday}`);
    });
    context.subscriptions.push(showStatusCmd);

    context.subscriptions.push(
        vscode.window.onDidChangeActiveTextEditor(editor => onEditorChange(editor)),
        vscode.window.onDidChangeWindowState(state => onWindowFocusChange(state)),
        vscode.workspace.onDidChangeWorkspaceFolders(() => onWorkspaceChange()),
        vscode.window.onDidChangeVisibleTextEditors(editors => onVisibleEditorsChange(editors))
    );

    // Initial check
    isWindowFocused = vscode.window.state.focused;
    const activeEditor = vscode.window.activeTextEditor;
    if (activeEditor && isWindowFocused) {
        startSession(activeEditor);
    }
}

function onEditorChange(editor: vscode.TextEditor | undefined) {
    endSession();
    if (editor && isWindowFocused) {
        startSession(editor);
    }
}

function onWindowFocusChange(state: vscode.WindowState) {
    if (!state.focused) {
        endSession();
        isWindowFocused = false;
    } else {
        isWindowFocused = true;
        const activeEditor = vscode.window.activeTextEditor;
        if (activeEditor) {
            startSession(activeEditor);
        }
    }
}

function onWorkspaceChange() {
    const activeEditor = vscode.window.activeTextEditor;
    if (activeEditor && isWindowFocused) {
        endSession();
        startSession(activeEditor);
    }
}

function onVisibleEditorsChange(editors: readonly vscode.TextEditor[]) {
    // If the active editor is no longer visible, end session
    const activeEditor = vscode.window.activeTextEditor;
    if (activeEditor && !editors.includes(activeEditor)) {
        endSession();
    }
}

function startSession(editor: vscode.TextEditor) {
    // Skip output channels and non-file schemes if possible, though 'file' and 'untitled' are common
    if (editor.document.uri.scheme !== 'file' && editor.document.uri.scheme !== 'untitled') {
        return;
    }

    const doc = editor.document;
    const language = doc.languageId;
    
    let workspace = 'No Workspace';
    let file = doc.fileName;

    const workspaceFolder = vscode.workspace.getWorkspaceFolder(doc.uri);
    if (workspaceFolder) {
        workspace = workspaceFolder.name;
        // Make path relative to workspace root
        file = vscode.workspace.asRelativePath(doc.uri, false);
    } else {
        // Just the file name if not in workspace
        const path = require('path');
        file = path.basename(doc.fileName);
    }

    currentSession = {
        file,
        workspace,
        language,
        startTime: new Date()
    };
    
    outputChannel.appendLine(`Started tracking: ${file} [${language}] in ${workspace}`);
}

function endSession() {
    if (!currentSession) {
        return;
    }

    const endTime = new Date();
    const durationMs = endTime.getTime() - currentSession.startTime.getTime();
    const durationSeconds = Math.floor(durationMs / 1000);

    const config = vscode.workspace.getConfiguration('activityTracker');
    const minDuration = config.get<number>('minSessionDuration') ?? 40;

    if (durationSeconds >= minDuration) {
        let uuidStr = '';
        if (typeof crypto.randomUUID === 'function') {
            uuidStr = crypto.randomUUID();
        } else {
            // fallback for older node
            uuidStr = crypto.randomBytes(16).toString('hex');
            uuidStr = `${uuidStr.slice(0,8)}-${uuidStr.slice(8,12)}-4${uuidStr.slice(13,16)}-a${uuidStr.slice(17,20)}-${uuidStr.slice(20)}`;
        }

        const event: ActivityEvent = {
            id: uuidStr,
            start: toIso8601WithTimezone(currentSession.startTime),
            end: toIso8601WithTimezone(endTime),
            duration_seconds: durationSeconds,
            source: 'vscode',
            context: {
                workspace: currentSession.workspace,
                file: currentSession.file,
                language: currentSession.language
            }
        };

        collectorClient.sendEvent(event);
        outputChannel.appendLine(`Ended tracking: ${currentSession.file} (${durationSeconds}s)`);
    } else {
        outputChannel.appendLine(`Session too short (${durationSeconds}s), discarded: ${currentSession.file}`);
    }

    currentSession = null;
}

export function deactivate() {
    endSession();
    if (collectorClient) {
        collectorClient.dispose();
    }
}
