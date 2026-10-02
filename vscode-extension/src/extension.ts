import * as vscode from 'vscode';
import * as crypto from 'crypto';
import { ActivityEvent, CollectorClient } from './collector-client';

interface CurrentSession {
    workspace: string;
    startTime: Date;
}

let currentSession: CurrentSession | null = null;
let isWindowFocused = true;
let outputChannel: vscode.OutputChannel;
let collectorClient: CollectorClient;
let statusBarItem: vscode.StatusBarItem;

const IDLE_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
let lastActivityTime: Date = new Date();
let isIdle: boolean = false;
let idleTimer: NodeJS.Timeout | null = null;

function getCurrentWorkspace(): string {
    const editor = vscode.window.activeTextEditor;
    if (editor && editor.document) {
        const folder = vscode.workspace.getWorkspaceFolder(editor.document.uri);
        if (folder) {
            return folder.name;
        }
    }
    const folders = vscode.workspace.workspaceFolders;
    if (folders && folders.length > 0) {
        return folders[0].name;
    }
    return 'No Workspace';
}

function resetIdleTimer() {
    const now = new Date();
    if (isIdle) {
        isIdle = false;
        if (outputChannel) {
            outputChannel.appendLine(`User active after idle; resuming tracking.`);
        }
        if (isWindowFocused) {
            startSession(getCurrentWorkspace(), now);
        }
    }
    lastActivityTime = now;

    if (idleTimer) {
        clearTimeout(idleTimer);
    }
    idleTimer = setTimeout(() => {
        onIdleTimeout();
    }, IDLE_TIMEOUT_MS);
}

function onIdleTimeout() {
    if (isIdle) {
        return;
    }
    isIdle = true;
    if (outputChannel) {
        outputChannel.appendLine(`No activity for 5 minutes. Ending session at last activity timestamp: ${lastActivityTime.toISOString()}`);
    }
    endSession(lastActivityTime);
}

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
            ? `Tracking workspace ${currentSession.workspace}`
            : 'Not currently tracking an active editor';
        vscode.window.showInformationMessage(`Activity Tracker: ${status}. Events sent today: ${collectorClient.eventsSentToday}`);
    });
    context.subscriptions.push(showStatusCmd);

    context.subscriptions.push(
        vscode.window.onDidChangeActiveTextEditor(editor => {
            resetIdleTimer();
            onEditorChange(editor);
        }),
        vscode.window.onDidChangeWindowState(state => onWindowFocusChange(state)),
        vscode.workspace.onDidChangeWorkspaceFolders(() => {
            resetIdleTimer();
            onWorkspaceChange();
        }),
        vscode.window.onDidChangeVisibleTextEditors(editors => onVisibleEditorsChange(editors)),
        vscode.workspace.onDidChangeTextDocument(() => resetIdleTimer()),
        vscode.window.onDidChangeTextEditorSelection(() => resetIdleTimer()),
        vscode.window.onDidChangeTextEditorVisibleRanges(() => resetIdleTimer())
    );

    // Initial check
    isWindowFocused = vscode.window.state.focused;
    resetIdleTimer();
    if (isWindowFocused) {
        startSession(getCurrentWorkspace());
    }
}

function onEditorChange(editor: vscode.TextEditor | undefined) {
    if (!isWindowFocused || isIdle) {
        return;
    }
    const newWorkspace = getCurrentWorkspace();
    if (currentSession) {
        if (currentSession.workspace === newWorkspace) {
            // A file change within the same workspace must not end the session.
            return;
        }
        endSession();
    }
    startSession(newWorkspace);
}

function onWindowFocusChange(state: vscode.WindowState) {
    if (!state.focused) {
        if (idleTimer) {
            clearTimeout(idleTimer);
            idleTimer = null;
        }
        endSession();
        isWindowFocused = false;
    } else {
        isWindowFocused = true;
        isIdle = false;
        resetIdleTimer();
        startSession(getCurrentWorkspace());
    }
}

function onWorkspaceChange() {
    if (!isWindowFocused || isIdle) {
        return;
    }
    const newWorkspace = getCurrentWorkspace();
    if (currentSession && currentSession.workspace !== newWorkspace) {
        endSession();
        startSession(newWorkspace);
    } else if (!currentSession) {
        startSession(newWorkspace);
    }
}

function onVisibleEditorsChange(editors: readonly vscode.TextEditor[]) {
    // No-op: workspace remains tracked even if tabs close
}

function startSession(workspace: string, startTime: Date = new Date()) {
    currentSession = {
        workspace,
        startTime: startTime
    };
    
    outputChannel.appendLine(`Started tracking workspace: ${workspace}`);
}

function endSession(explicitEndTime?: Date) {
    if (!currentSession) {
        return;
    }

    const endTime = explicitEndTime ?? new Date();
    const durationMs = endTime.getTime() - currentSession.startTime.getTime();
    const durationSeconds = Math.max(0, Math.floor(durationMs / 1000));

    const config = vscode.workspace.getConfiguration('activityTracker');
    const minDuration = config.get<number>('minSessionDuration') ?? 2;

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
                workspace: currentSession.workspace
            }
        };

        collectorClient.sendEvent(event);
        outputChannel.appendLine(`Ended tracking workspace: ${currentSession.workspace} (${durationSeconds}s)`);
    } else {
        outputChannel.appendLine(`Session too short (${durationSeconds}s), discarded workspace: ${currentSession.workspace}`);
    }

    currentSession = null;
}

export function deactivate() {
    if (idleTimer) {
        clearTimeout(idleTimer);
        idleTimer = null;
    }
    endSession();
    if (collectorClient) {
        collectorClient.dispose();
    }
}
