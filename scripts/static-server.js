const http = require('http');
const fs = require('fs');
const path = require('path');

const root = process.cwd();
const port = Number(process.env.PORT || 8080);

const mime = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
};

function safeResolve(urlPath) {
  const clean = decodeURIComponent(urlPath.split('?')[0]).replace(/^\/+/, '');
  const rel = clean === '' ? 'index.html' : clean;
  const abs = path.resolve(root, rel);
  if (!abs.startsWith(root)) return null;
  return abs;
}

const server = http.createServer((req, res) => {
  const abs = safeResolve(req.url || '/');
  if (!abs) {
    res.statusCode = 403;
    res.end('Forbidden');
    return;
  }

  let filePath = abs;
  if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
    filePath = path.join(filePath, 'index.html');
  }

  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    res.statusCode = 404;
    res.end('Not Found');
    return;
  }

  const ext = path.extname(filePath).toLowerCase();
  res.setHeader('Content-Type', mime[ext] || 'application/octet-stream');
  fs.createReadStream(filePath).pipe(res);
});

server.listen(port, '127.0.0.1', () => {
  // eslint-disable-next-line no-console
  console.log(`Static server on http://127.0.0.1:${port}`);
});

