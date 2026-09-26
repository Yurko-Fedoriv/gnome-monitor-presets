import Gio from 'gi://Gio';

export function run(path, ...args) {
    return new Promise((resolve, reject) => {
        const launcher = new Gio.SubprocessLauncher({flags:
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE});
        launcher.setenv('MONITOR_ACTION_REQUESTED', String(Date.now() / 1000), true);
        const process = launcher.spawnv(['/usr/bin/python3', `${path}/backend.py`, ...args]);
        process.communicate_utf8_async(null, null, (source, result) => {
            try {
                const [, stdout, stderr] = source.communicate_utf8_finish(result);
                const data = JSON.parse(stdout || '{}');
                if (!source.get_successful() || data.error)
                    throw new Error(data.error || stderr || 'Monitor helper failed');
                resolve(data);
            } catch (error) {
                reject(error);
            }
        });
    });
}

export function count(layout) {
    return layout.logical.reduce((n, group) => n + group.monitors.length, 0);
}

export function summary(layout) {
    return layout.logical.map(group => group.monitors.map(m =>
        `${m.spec[0]}${group.primary ? '*' : ''}: ${m.width}×${m.height} · ${Number(m.refresh.toFixed(2))} Hz · ${Math.round(group.scale * 100)}% · X: ${group.x}, Y: ${group.y}`
    ).join('\n')).join('\n');
}
