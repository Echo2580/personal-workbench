// A module exposes only mountPage and optional mountSettings to the shell.
export const moduleLoaders={projects:()=>import('../modules/projects/index.js'),tasks:()=>import('../modules/tasks/page.js')};
