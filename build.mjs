import { mkdir, copyFile, cp, readFile, writeFile } from 'node:fs/promises';
const siteUrl = (process.env.PUBLIC_SITE_URL || (process.env.VERCEL_PROJECT_PRODUCTION_URL ? 'https://' + process.env.VERCEL_PROJECT_PRODUCTION_URL : 'https://www.daisquee.it')).replace(/\/$/, '');
const files = ['index.html','appartamento-suite-max.html','appartamento-michele.html','appartamento-rosa-e-romeo.html','admin.html','pagamento.html','site.css','editorial.css','site.js','admin.css','admin.js','robots.txt','sitemap.xml','llms.txt','booking.js','chi-siamo.html','servizi.html','contatti.html','appartamenti.html','domande-frequenti.html','possagno-canova.html','bassano-del-grappa.html','asolo.html','maser-palladio.html','carlo-scarpa-brion.html','monte-grappa.html','pedemontana-in-bici.html','terre-del-prosecco.html','intorno-a-noi.html','navigazione-stefanato.html','flyvenice.html','airsports-montegrappa.html','rafting-brenta.html','amici-partners.html','prenota.html','disponibilita.html'];
await mkdir('public', { recursive: true });
for (const file of files) {
  if (/\.(html|xml|txt)$/.test(file)) {
    let text = await readFile(file, 'utf8');
    if (file.endsWith('.html')) {
      text = text.replace(/<(?:meta|link)[^>]+>|<script type="application\/ld\+json">[\s\S]*?<\/script>/g, tag => tag.replaceAll('https://www.daisquee.it',siteUrl));
    } else text = text.replaceAll('https://www.daisquee.it',siteUrl);
    await writeFile('public/'+file,text);
  } else await copyFile(file,'public/'+file);
}
await cp('assets','public/assets',{recursive:true});
console.log('Static site ready: ' + siteUrl);
