import express from 'express';
import path from 'path';
const app = express();
const WEB_DIR = path.join(__dirname, 'web');
const FOODY_API = process.env.FOODY_API || '';
app.get('/config.js', (req,res) => {
  res.type('application/javascript').send(`window.foodyApi=${JSON.stringify(FOODY_API)};`);
});
app.use('/web', express.static(WEB_DIR, { index: 'index.html', extensions: ['html'] }));
app.use(express.static(WEB_DIR, { index: 'index.html', extensions: ['html'] }));
app.get('/health', (req,res)=>res.json({ok:true}));
app.get('/', (req,res)=>res.redirect('/web/buyer/'));
const PORT = process.env.PORT || 8080;
app.listen(PORT, ()=>console.log('Foody web listening on', PORT));
