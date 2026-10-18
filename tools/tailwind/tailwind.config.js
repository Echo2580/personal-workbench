/** Tailwind build config. Preflight is disabled on purpose: the legacy project pages
 *  (app/web/modules/projects/styles.css + shell.css) must keep their current look
 *  during the shell transition, and preflight would reset their element styles.
 *  Content globs are resolved from this file so the build works from any CWD. */
const path = require('path');
const web = path.resolve(__dirname, '../../app/web');

module.exports = {
  content: [path.join(web, 'index.html'), path.join(web, '**/*.js')],
  corePlugins: {preflight: false},
  theme: {extend: {}},
  plugins: [],
};
