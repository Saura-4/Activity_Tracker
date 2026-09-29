import * as http from 'http';
import * as vscode from 'vscode';
import * as crypto from 'crypto';

export interface ActivityEvent {
    id: string;        // UUID
    start: string;     // ISO-8601 with timezone
    end: string;       // ISO-8601 with timezone
    duration_seconds: number;
    source: 'vscode';
    context: {
        workspace: string;   // workspace/folder name
        file: string;        // relative file path within workspace
        language: string;    // language ID (python, typescript, etc.)
    };
}

export class CollectorClient {
    private queue: ActivityEvent[] = [];
    private maxQueueSize = 500;
    private retryTimer: NodeJS.Timeout | null = null;
    public eventsSentToday = 0;

    constructor(private outputChannel: vscode.OutputChannel) {
        this.startRetryTimer();
    }

    private startRetryTimer() {
        this.retryTimer = setInterval(() => {
            this.flushQueue();
        }, 30000);
    }

    public async sendEvent(event: ActivityEvent): Promise<boolean> {
        const config = vscode.workspace.getConfiguration('activityTracker');
        const urlString = config.get<string>('collectorUrl') || 'http://127.0.0.1:8765';
        
        try {
            const url = new URL(urlString + '/event');
            const data = JSON.stringify(event);

            return new Promise((resolve) => {
                const req = http.request(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Content-Length': Buffer.byteLength(data)
                    }
                }, (res) => {
                    if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
                        this.eventsSentToday++;
                        resolve(true);
                    } else {
                        this.outputChannel.appendLine(`Collector returned status code ${res.statusCode}`);
                        this.enqueue(event);
                        resolve(false);
                    }
                });

                req.on('error', (err) => {
                    this.outputChannel.appendLine(`Error sending event: ${err.message}`);
                    this.enqueue(event);
                    resolve(false);
                });

                req.write(data);
                req.end();
            });
        } catch (e) {
            this.outputChannel.appendLine(`Invalid collector URL: ${urlString}`);
            this.enqueue(event);
            return false;
        }
    }

    private enqueue(event: ActivityEvent) {
        if (this.queue.length < this.maxQueueSize) {
            this.queue.push(event);
        } else {
            this.outputChannel.appendLine(`Queue full, dropping event ${event.id}`);
        }
    }

    public async flushQueue() {
        if (this.queue.length === 0) return;
        
        this.outputChannel.appendLine(`Flushing queue of ${this.queue.length} events...`);
        const queueCopy = [...this.queue];
        this.queue = [];
        
        for (const event of queueCopy) {
            await this.sendEvent(event);
        }
    }

    public dispose() {
        if (this.retryTimer) {
            clearInterval(this.retryTimer);
            this.retryTimer = null;
        }
        this.flushQueue();
    }
}
