const BENIGN = new Set(['EBADF', 'EPIPE', 'ERR_STREAM_DESTROYED', 'ERR_STDOUT_CLOSED']);

const ignore = (error) => {
  if (error && BENIGN.has(error.code)) return;
  throw error;
};

// The seekdb embedded engine can close the inherited stdio descriptors once it
// starts; log writes must not take the API server down when that happens.
for (const stream of [process.stdout, process.stderr]) {
  stream.on?.('error', (error) => {
    if (!error || !BENIGN.has(error.code)) throw error;
  });
}

export const log = (...args) => {
  try {
    console.log(...args);
  } catch (error) {
    ignore(error);
  }
};

export const logError = (...args) => {
  try {
    console.error(...args);
  } catch (error) {
    ignore(error);
  }
};
