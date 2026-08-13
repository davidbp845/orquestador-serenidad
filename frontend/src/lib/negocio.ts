import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { config } from 'dotenv';
import { load } from 'js-yaml';

// Lee config/business.yaml en build-time (Node, no en el navegador):
// mismo fichero que usa el backend Python, así el nombre/tono del
// negocio no se duplica a mano en el frontend. Cambiar de negocio es
// solo tocar ese YAML, igual que ya documenta CLAUDE.md.
//
// RAIZ_REPO en vez de import.meta.url: tras el bundling de producción, el
// chunk final vive en una profundidad de directorios distinta a la del
// fichero fuente, así que una ruta relativa a import.meta.url se rompe en
// `astro build`. process.cwd() sigue siendo la raíz de frontend/ (desde
// donde siempre se lanza `astro dev`/`astro build`), así que basta con
// subir un nivel.
const RAIZ_REPO = resolve(process.cwd(), '..');

// Se carga el .env de la raíz del repo (no frontend/.env, que es un
// fichero distinto usado para PUBLIC_*) para que CONFIG_PATH definida
// ahí llegue igual que a main.py/panel_empleados (issue #88) — sin
// esto, CONFIG_PATH solo funcionaba si se exportaba a mano en el shell.
// dotenv no sobreescribe variables ya presentes en process.env, igual
// que python-dotenv.
config({ path: resolve(RAIZ_REPO, '.env'), quiet: true });

// CONFIG_PATH (opcional, #73) sobreescribe qué business.yaml se lee —
// para desplegar con datos de negocio reales sin forkear el repo ni
// commitearlos encima del business.yaml de demo. Sin ella, mismo
// comportamiento de siempre. No lleva prefijo PUBLIC_: este módulo
// solo corre en Node (build-time), nunca llega al navegador. Si es una
// ruta relativa, se resuelve contra RAIZ_REPO (no process.cwd()) para
// que un mismo valor relativo de CONFIG_PATH signifique lo mismo en
// main.py, el panel y aquí — los tres corren con la raíz del repo como
// cwd salvo el frontend (issue #88).

interface ServicioNegocio {
  id: string;
  nombre: string;
  duracion_minutos: number;
  precio: number;
}

interface CtaCitaConfig {
  texto_corto: string;
  texto_largo: string;
  mensaje: string;
}

interface DireccionNegocio {
  calle: string;
  localidad: string;
  codigo_postal: string;
  pais: string;
}

// Paleta de colores y tipografía del negocio (config/schema.py::TemaConfig,
// issue #76). Todo opcional: sin campos definidos, LayoutBase.astro no
// inyecta ningún override y el frontend usa la paleta/tipografía neutra
// por defecto de global.css. Las fuentes son autoalojadas (.woff2 servido
// por el propio frontend), no Google Fonts.
interface TemaNegocio {
  color_fondo?: string;
  color_superficie?: string;
  color_texto?: string;
  color_texto_suave?: string;
  color_borde?: string;
  color_acento?: string;
  color_acento_suave?: string;
  fuente_titulo_url?: string;
  fuente_cuerpo_url?: string;
}

// Mismas claves de día que horario_semanal (config/schema.py):
// lunes..domingo, cada una ["HH:MM", "HH:MM"]. Usado solo para el
// JSON-LD de SEO (DatosEstructurados.astro) — ver issue #75.
type HorarioApertura = Record<string, [string, string]>;

interface ConfigNegocio {
  nombre: string;
  tono?: string;
  servicios?: ServicioNegocio[];
  logo_url?: string;
  logo_compacto_url?: string;
  hero_titulo?: string;
  hero_subtitulo: string;
  imagen_fondo_url?: string;
  tema?: TemaNegocio;
  cta_cita?: CtaCitaConfig;
  vault_obsidian?: string;
  direccion?: DireccionNegocio;
  mapa_url?: string;
  instrucciones_llegada?: string;
  telefono?: string;
  email?: string;
  horario_apertura?: HorarioApertura;
}

const rutaConfig = resolve(RAIZ_REPO, process.env.CONFIG_PATH ?? 'config/business.yaml');

export const negocio = load(readFileSync(rutaConfig, 'utf-8')) as ConfigNegocio;
