export const projectsApi=api=>({snapshot:signal=>api.request('/projects',{signal}),recipes:(id,signal)=>api.request(`/projects/${id}/recipes`,{signal})});
