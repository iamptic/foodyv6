import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const WEB_DIR = path.join(__dirname, 'web');
app.get('/config.js', (req,res) => {
  res.type('application/javascript').send(`window.foodyApi=${JSON.stringify(FOODY_API)};`);
});
app.use('/web', express.static(WEB_DIR, { index: 'index.html', extensions: ['html'] }));
app.use(express.static(WEB_DIR, { index: 'index.html', extensions: ['html'] }));
app.get('/health', (req,res)=>res.json({ok:true}));
app.get('/', (req,res)=>res.redirect('/web/buyer/'));
const PORT = process.env.PORT || 8080;
app.listen(PORT, ()=>console.log('Foody web listening on', PORT));
