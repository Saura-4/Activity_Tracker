import * as vscode from 'vscode';
import * as crypto from 'crypto';
import { ActivityEvent, CollectorClient } from './collector-client';

interface CurrentSession {
    id: string;
    workspace: string;
    startTime: Date;
    lastCheckpointTime: number;
}

let currentSession: CurrentSession | null = null;
let isWindowFocused = true;
let outputChannel: vscode.OutputChannel;
let collectorClient: CollectorClient;
let statusBarItem: vscode.StatusBarItem;
let checkpointTimer: NodeJS.Timeout | null = null;

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

function getDeterministicSessionId(startTime: Date, workspace: string): string {
    const hash = crypto.createHash('sha256')
        .update(`vscode:${startTime.toISOString()}:${workspace}`)
        .digest('hex');
    return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
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
            onEditorChange(editor);
        }),
        vscode.window.onDidChangeWindowState(state => onWindowFocusChange(state)),
        vscode.workspace.onDidChangeWorkspaceFolders(() => {
            onWorkspaceChange();
        })
    );

    // Periodic 60s checkpoint for crash durability
    checkpointTimer = setInterval(() => {
        checkpointSession();
    }, 60000);

    // Initial check
    isWindowFocused = vscode.window.state.focused;
    if (isWindowFocused) {
        startSession(getCurrentWorkspace());
    }
}

function onEditorChange(editor: vscode.TextEditor | undefined) {
    if (!isWindowFocused) {
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
        endSession();
        isWindowFocused = false;
    } else {
        isWindowFocused = true;
        startSession(getCurrentWorkspace());
    }
}

function onWorkspaceChange() {
    if (!isWindowFocused) {
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

function startSession(workspace: string, startTime: Date = new Date()) {
    currentSession = {
        id: getDeterministicSessionId(startTime, workspace),
        workspace,
        startTime: startTime,
        lastCheckpointTime: Date.now()
    };
    
    outputChannel.appendLine(`Started tracking workspace: ${workspace} (ID: ${currentSession.id})`);
}

function checkpointSession() {
    if (!currentSession || !isWindowFocused) {
        return;
    }

    const now = new Date();
    const durationMs = now.getTime() - currentSession.startTime.getTime();
    const durationSeconds = Math.max(0, Math.floor(durationMs / 1000));

    const config = vscode.workspace.getConfiguration('activityTracker');
    const minDuration = config.get<number>('minSessionDuration') ?? 2;

    if (durationSeconds >= minDuration) {
        const event: ActivityEvent = {
            id: currentSession.id,
            start: toIso8601WithTimezone(currentSession.startTime),
            end: toIso8601WithTimezone(now),
            duration_seconds: durationSeconds,
            source: 'vscode',
            context: {
                workspace: currentSession.workspace
            }
        };

        collectorClient.sendEvent(event);
        currentSession.lastCheckpointTime = Date.now();
        outputChannel.appendLine(`Checkpointed workspace: ${currentSession.workspace} (${durationSeconds}s)`);
    }
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
        const event: ActivityEvent = {
            id: currentSession.id,
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
    if (checkpointTimer) {
        clearInterval(checkpointTimer);
        checkpointTimer = null;
    }
    endSession();
    if (collectorClient) {
        collectorClient.dispose();
    }
}
