import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'
import { setupApiClient } from './lib/api-client'

setupApiClient()

const app = mount(App, {
  target: document.getElementById('app')!,
})

export default app
