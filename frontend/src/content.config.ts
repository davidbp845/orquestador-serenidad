import { resolve } from 'node:path';
import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';
import { negocio } from './lib/negocio';

// vault_obsidian (business.yaml) es relativa a la raíz del repo (mismo
// criterio que usan main.py/obsidian_ingest.py, que corren con ese cwd),
// así que se resuelve subiendo un nivel desde process.cwd() (frontend/) —
// mismo patrón que rutaConfig en lib/negocio.ts. Antes esta ruta estaba
// hardcodeada a '../vault_negocio', ignorando tanto vault_obsidian como
// el override CONFIG_PATH (#74).
const rutaVault = resolve(process.cwd(), '..', negocio.vault_obsidian ?? './vault_negocio');

const vault = defineCollection({
  loader: glob({ pattern: '**/*.md', base: rutaVault }),
  schema: z
    .object({
      categoria: z.string().optional(),
      tags: z.array(z.string()).optional(),
      publicar_web: z.boolean().default(false),
      orden: z.number().optional(),
      // Texto corto para la tarjeta de la sección de contenido público;
      // el cuerpo completo de la nota se muestra al abrirla. Solo hace
      // falta si la nota se publica en la web.
      resumen: z.string().optional(),
    })
    .passthrough()
    .refine((data) => !data.publicar_web || Boolean(data.resumen?.trim()), {
      message: 'resumen es obligatorio cuando publicar_web es true',
      path: ['resumen'],
    }),
});

export const collections = { vault };
