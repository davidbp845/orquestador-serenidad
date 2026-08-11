import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { load } from 'js-yaml';

// Lee config/business.yaml en build-time (Node, no en el navegador):
// mismo fichero que usa el backend Python, así el nombre/tono del
// negocio no se duplica a mano en el frontend. Cambiar de negocio es
// solo tocar ese YAML, igual que ya documenta CLAUDE.md.
//
// Se resuelve contra process.cwd() (la raíz de frontend/, desde donde
// siempre se lanza `astro dev`/`astro build`) en vez de import.meta.url:
// tras el bundling de producción, el chunk final vive en una
// profundidad de directorios distinta a la del fichero fuente, así
// que una ruta relativa a import.meta.url se rompe en `astro build`.
interface ServicioNegocio {
  id: string;
  nombre: string;
  duracion_minutos: number;
  precio: number;
}

interface ConfigNegocio {
  nombre: string;
  tono?: string;
  servicios?: ServicioNegocio[];
  logo_url?: string;
  hero_titulo?: string;
  hero_subtitulo: string;
  imagen_fondo_url?: string;
}

const rutaConfig = resolve(process.cwd(), '../config/business.yaml');

export const negocio = load(readFileSync(rutaConfig, 'utf-8')) as ConfigNegocio;
