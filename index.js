const express = require('express');
const path = require('path');
const axios = require('axios');
const cheerio = require('cheerio');
const sqlite3 = require('sqlite3').verbose();
const app = express();
const PORT = process.env.PORT || 4000;
const DB_FILE = path.join(__dirname, 'manga.db');

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const db = new sqlite3.Database(DB_FILE, (err) => {
  if (err) console.error(err.message);
  else console.log('Conectado a la base de datos SQLite');
});

const dbRun = (sql, params = []) =>
  new Promise((resolve, reject) => {
    db.run(sql, params, function (err) {
      if (err) return reject(err);
      resolve(this);
    });
  });

const dbGet = (sql, params = []) =>
  new Promise((resolve, reject) => {
    db.get(sql, params, (err, row) => {
      if (err) return reject(err);
      resolve(row);
    });
  });

const dbAll = (sql, params = []) =>
  new Promise((resolve, reject) => {
    db.all(sql, params, (err, rows) => {
      if (err) return reject(err);
      resolve(rows);
    });
  });

const normalizarCapitulo = (valor) => {
  if (valor === null || valor === undefined) return '';
  const numero = parseFloat(valor);
  return Number.isNaN(numero) ? String(valor).trim() : String(numero);
};

const insertarManga = (nombre, url) =>
  new Promise((resolve, reject) => {
    db.run(
      'INSERT INTO manga (nombre, url) VALUES (?, ?)',
      [nombre, url],
      function (err) {
        if (err) return reject(err);
        resolve(this.lastID);
      }
    );
  });

const obtenerMangaPorUrl = (url) =>
  new Promise((resolve, reject) => {
    db.get(
      `SELECT m.id
       FROM manga m
       WHERE m.url = ?`,
      [url],
      (err, row) => {
        if (err) return reject(err);
        resolve(row || null);
      }
    );
  });

const obtenerMangaConProgreso = (id) =>
  new Promise((resolve, reject) => {
    db.get(
      `SELECT m.id,
              m.nombre,
              m.url,
              m.ultimo_capitulo,
              m.fecha_consulta,
              COALESCE(p.capitulo_actual, m.ultimo_capitulo, '0') AS capitulo_actual,
              COALESCE(d.total_capitulos, 0) AS total_capitulos,
              COALESCE(d.total_descargados, 0) AS total_descargados
       FROM manga m
       LEFT JOIN progreso_manga p ON m.id = p.manga_id
       LEFT JOIN (
         SELECT manga_id,
                COUNT(*) AS total_capitulos,
                SUM(CASE WHEN descargado = 1 THEN 1 ELSE 0 END) AS total_descargados
         FROM descargas
         GROUP BY manga_id
       ) d ON m.id = d.manga_id
       WHERE m.id = ?`,
      [id],
      (err, row) => {
        if (err) return reject(err);
        resolve(row || null);
      }
    );
  });

// Crear tabla si no existe
db.run(`CREATE TABLE IF NOT EXISTS manga (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT UNIQUE,
    url TEXT,
    ultimo_capitulo TEXT,
    fecha_consulta TEXT,
    fecha_nuevo_capitulo TEXT
)`);

db.run(
  `ALTER TABLE manga ADD COLUMN fecha_nuevo_capitulo TEXT`,
  (err) => {
    if (err && !/duplicate column name/i.test(err.message)) {
      console.error('Error al preparar la columna fecha_nuevo_capitulo:', err);
    }
  }
);

// Agregar tabla para el progreso del manga
db.run(`CREATE TABLE IF NOT EXISTS progreso_manga (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manga_id INTEGER UNIQUE,
    capitulo_actual TEXT,
    FOREIGN KEY (manga_id) REFERENCES manga(id)
)`);

db.run(
  `CREATE TABLE IF NOT EXISTS descargas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manga_id INTEGER NOT NULL,
    nombre_capitulo TEXT NOT NULL,
    enlace TEXT,
    numero_capitulo TEXT,
    orden INTEGER,
    descargado INTEGER DEFAULT 0,
    fecha_registro TEXT DEFAULT CURRENT_TIMESTAMP,
    fecha_descarga TEXT,
    UNIQUE(manga_id, nombre_capitulo),
    FOREIGN KEY (manga_id) REFERENCES manga(id) ON DELETE CASCADE
  )`,
  (err) => {
    if (err) {
      console.error('Error al preparar la tabla de descargas:', err);
    }
  }
);

// Obtener el progreso de lectura de un manga
app.get('/progreso/:id', async (req, res) => {
  try {
    const { id } = req.params;

    db.get(
      'SELECT capitulo_actual FROM progreso_manga WHERE manga_id = ?',
      [id],
      (err, row) => {
        if (err) {
          console.error('Error en la base de datos:', err);
          return res.status(500).json({ error: 'Error en la base de datos' });
        }

        if (!row) {
          return res.json({ capitulo_actual: '0' }); // Devuelve '0' si no hay resultado
        }

        res.json({ capitulo_actual: row.capitulo_actual });
      }
    );
  } catch (error) {
    console.error('Error en el servidor:', error);
    res.status(500).json({ error: 'Error interno del servidor' });
  }
});


// Actualizar el progreso de lectura de un manga
app.post('/progreso/:id', (req, res) => {
  const { id } = req.params;
  const { capitulo_actual } = req.body;

  if (!capitulo_actual) {
    return res.status(400).json({ error: 'El capítulo actual es requerido' });
  }

  db.run(
    'INSERT INTO progreso_manga (manga_id, capitulo_actual) VALUES (?, ?) ON CONFLICT(manga_id) DO UPDATE SET capitulo_actual = ?',
    [id, capitulo_actual, capitulo_actual],
    (err) => {
      if (err)
        return res
          .status(500)
          .json({ error: 'Error al actualizar el progreso' });
      res.json({ mensaje: 'Progreso actualizado exitosamente' });
    }
  );
});

// Obtener la lista de mangas con progreso
app.get('/mangas', (req, res) => {
  const query = `
        SELECT m.id,
               m.nombre,
               m.url,
               m.ultimo_capitulo,
               m.fecha_consulta,
               COALESCE(p.capitulo_actual, m.ultimo_capitulo) AS capitulo_actual,
               COALESCE(d.total_capitulos, 0) AS total_capitulos,
               COALESCE(d.total_descargados, 0) AS total_descargados
        FROM manga m 
        LEFT JOIN progreso_manga p ON m.id = p.manga_id
        LEFT JOIN (
          SELECT manga_id,
                 COUNT(*) AS total_capitulos,
                 SUM(CASE WHEN descargado = 1 THEN 1 ELSE 0 END) AS total_descargados
          FROM descargas
          GROUP BY manga_id
        ) d ON m.id = d.manga_id`;

  db.all(query, [], (err, rows) => {
    if (err)
      return res.status(500).json({ error: 'Error en la base de datos' });
    res.json(rows);
  });
});

// Agregar un nuevo manga con URL
app.post('/mangas', async (req, res) => {
  const { nombre, url } = req.body;
  if (!nombre || !url)
    return res.status(400).json({ error: 'Nombre y URL son requeridos' });

  try {
    const nombreLimpio = nombre.trim();
    const urlLimpia = url.trim();
    if (!nombreLimpio || !urlLimpia) {
      return res
        .status(400)
        .json({ error: 'Nombre y URL son requeridos', campo: 'form' });
    }

    const existente = await obtenerMangaPorUrl(urlLimpia);
    if (existente) {
      const mangaExistente = await obtenerMangaConProgreso(existente.id);
      return res.status(409).json({
        error: 'La URL ya está registrada',
        manga: mangaExistente,
      });
    }

    const nuevoId = await insertarManga(nombreLimpio, urlLimpia);

    let resultadoActualizacion = null;
    try {
      resultadoActualizacion = await actualizarMangaPorId(nuevoId);
    } catch (errorActualizacion) {
      console.error(
        'No se pudo actualizar automáticamente el nuevo manga:',
        errorActualizacion
      );
    }

    const manga = await obtenerMangaConProgreso(nuevoId);
    if (!manga) {
      return res
        .status(500)
        .json({ error: 'No se pudo recuperar el manga recién agregado' });
    }

    const respuesta = {
      ...manga,
      nuevo: Boolean(resultadoActualizacion?.nuevo),
    };

    if (
      resultadoActualizacion &&
      resultadoActualizacion.ultimo_capitulo !== undefined &&
      resultadoActualizacion.ultimo_capitulo !== null
    ) {
      respuesta.ultimo_capitulo = resultadoActualizacion.ultimo_capitulo;
    }
    if (
      resultadoActualizacion &&
      resultadoActualizacion.capitulo_actual !== undefined &&
      resultadoActualizacion.capitulo_actual !== null &&
      resultadoActualizacion.capitulo_actual !== ''
    ) {
      respuesta.capitulo_actual = resultadoActualizacion.capitulo_actual;
    }
    if (resultadoActualizacion && resultadoActualizacion.fecha) {
      respuesta.fecha_consulta = resultadoActualizacion.fecha;
    }

    if (
      respuesta.capitulo_actual === undefined ||
      respuesta.capitulo_actual === null ||
      respuesta.capitulo_actual === ''
    ) {
      respuesta.capitulo_actual = '0';
    }
    if (
      respuesta.ultimo_capitulo === undefined ||
      respuesta.ultimo_capitulo === null ||
      respuesta.ultimo_capitulo === ''
    ) {
      respuesta.ultimo_capitulo = '-';
    }
    if (!respuesta.fecha_consulta) {
      respuesta.fecha_consulta = '-';
    }

    res.json({
      ...respuesta,
      mensaje: 'Manga agregado correctamente',
    });
  } catch (error) {
    console.error('Error al agregar manga:', error);
    if (
      error &&
      typeof error.message === 'string' &&
      error.message.includes('UNIQUE constraint failed')
    ) {
      return res
        .status(409)
        .json({ error: 'El manga ya existe en la base de datos' });
    }
    res.status(500).json({ error: 'Error al agregar manga' });
  }
});

// Consultar un manga y actualizar su capítulo (por ID)
app.get('/manga/:id', async (req, res) => {
  const { id } = req.params;
  if (!id) return res.status(400).json({ error: 'Falta el ID del manga' });

  try {
    const resultado = await actualizarMangaPorId(id);
    console.log(resultado);
    res.json(resultado); // Enviar la respuesta con los datos obtenidos
  } catch (error) {
    console.error('Error capturado:', error);
    res.status(500).json(error); // Enviar el error en formato JSON con status 500
  }
});

async function actualizarMangaPorId(id) {
  return new Promise((resolve, reject) => {
    db.get('SELECT url FROM manga WHERE id = ?', [id], async (err, row) => {
      if (err) {
        console.error('Error al consultar el manga:', err);
        return reject({ error: 'Error en la base de datos' });
      }
      if (!row) return reject({ error: 'Manga no encontrado' });

      try {
        const nuevoCapitulo = await obtenerUltimoCapitulo(row.url);
        if (!nuevoCapitulo)
          return reject({ error: 'No se pudo obtener el capítulo' });

        const fechaActual = new Date();
        const fechaActualTexto = fechaActual.toLocaleString('es-MX');
        const fechaActualISO = fechaActual.toISOString();

        db.get(
          `SELECT m.id,
                  m.nombre,
                  m.url,
                  m.ultimo_capitulo,
                  m.fecha_consulta,
                  p.capitulo_actual,
                  m.fecha_nuevo_capitulo
           FROM manga m
           LEFT JOIN progreso_manga p ON m.id = p.manga_id 
           WHERE m.id = ?`,
          [id],
          (err, row) => {
            if (err) {
              console.error('Error al obtener datos del manga:', err);
              return reject({ error: 'Error en la base de datos' });
            }
            if (!row)
              return reject({
                error: 'Manga no encontrado en la segunda consulta',
              });

            const ultimoNormalizado = normalizarCapitulo(
              row.ultimo_capitulo
            );
            const nuevoNormalizado = normalizarCapitulo(nuevoCapitulo);
            const capituloCambio = ultimoNormalizado !== nuevoNormalizado;

            let mostrarNuevo = capituloCambio;

            const fechaNuevoCapitulo =
              row.fecha_nuevo_capitulo &&
              !Number.isNaN(
                new Date(row.fecha_nuevo_capitulo).getTime()
              )
                ? new Date(row.fecha_nuevo_capitulo)
                : null;

            if (!mostrarNuevo && fechaNuevoCapitulo) {
              const horasDesdeNuevo =
                (fechaActual - fechaNuevoCapitulo) / (1000 * 60 * 60);
              if (horasDesdeNuevo < 24) {
                mostrarNuevo = true;
              }
            }

            const progresoNormalizado = normalizarCapitulo(
              row.capitulo_actual
            );
            const progresoVacio = progresoNormalizado === '';
            const ultimoEsNumerico =
              ultimoNormalizado !== '' &&
              Number.isFinite(parseFloat(ultimoNormalizado));
            const progresoInicial = ultimoEsNumerico
              ? ultimoNormalizado
              : '0';
            const progresoParaRespuesta =
              progresoNormalizado !== ''
                ? progresoNormalizado
                : capituloCambio
                ? progresoInicial
                : '0';

            const resolverConDescargas = () => {
              const respuestaBase = {
                mensaje: mostrarNuevo
                  ? 'Nuevo capítulo disponible'
                  : 'No hay capítulos nuevos',
                ultimo_capitulo: nuevoCapitulo,
                capitulo_actual: progresoParaRespuesta,
                fecha: fechaActualTexto,
                nuevo: mostrarNuevo,
              };
              obtenerCapitulosDescargas(id)
                .then((capitulosDescargas) => {
                  const resumenDescargas =
                    construirResumenDescargas(capitulosDescargas);
                  resolve({
                    ...respuestaBase,
                    total_capitulos: resumenDescargas.total,
                    total_descargados: resumenDescargas.descargados,
                  });
                })
                .catch((errorResumen) => {
                  console.error(
                    'Error al obtener resumen de descargas:',
                    errorResumen
                  );
                  resolve({
                    ...respuestaBase,
                    total_capitulos: 0,
                    total_descargados: 0,
                  });
                });
            };

            if (capituloCambio) {
              db.run(
                `UPDATE manga 
                 SET ultimo_capitulo = ?, fecha_consulta = ?, fecha_nuevo_capitulo = ? 
                 WHERE id = ?`,
                [nuevoNormalizado, fechaActualTexto, fechaActualISO, id],
                (err) => {
                  if (err) {
                    console.error('Error al actualizar el manga:', err);
                    return reject({ error: 'Error al actualizar datos' });
                  }
                  if (progresoVacio) {
                    db.run(
                      `INSERT INTO progreso_manga (manga_id, capitulo_actual)
                       VALUES (?, ?)
                       ON CONFLICT(manga_id) DO UPDATE SET capitulo_actual = excluded.capitulo_actual`,
                      [id, progresoInicial],
                      (err) => {
                        if (err) {
                          console.error(
                            'Error al ajustar progreso automáticamente:',
                            err
                          );
                        }
                        resolverConDescargas();
                      }
                    );
                  } else {
                    resolverConDescargas();
                  }
                }
              );
            } else {
              db.run(
                `UPDATE manga SET fecha_consulta = ? WHERE id = ?`,
                [fechaActualTexto, id],
                (err) => {
                  if (err) {
                    console.error('Error al actualizar la fecha:', err);
                    return reject({ error: 'Error al actualizar datos' });
                  }
                  resolverConDescargas();
                }
              );
            }
          }
        );
      } catch (error) {
        console.error('Error en obtenerUltimoCapitulo:', error);
        reject({ error: 'Error al obtener el último capítulo' });
      }
    });
  });
}


// Obtener el último capítulo de la web
async function obtenerUltimoCapitulo(url) {
  try {
    const response = await axios.get(url);
    const $ = cheerio.load(response.data);
    const capituloTexto = $('.col-xs-12.chapter h4 a').first().text().trim();
    const match = capituloTexto.match(/Capitulo (\d+(\.\d+)?)/i); // Soporta enteros y decimales
    return match ? parseFloat(match[1]) : 'No encontrado';
  } catch (error) {
    console.error('Error al obtener datos de la web:', error);
    return null;
  }
}

const resolverUrlRelativa = (base, enlace) => {
  if (!enlace) return null;
  try {
    return new URL(enlace, base).href;
  } catch (error) {
    console.error('No se pudo resolver la URL del capítulo:', error);
    return enlace;
  }
};

const extraerNumeroCapitulo = (texto) => {
  if (!texto) return null;
  const match = String(texto).match(/(\d+(\.\d+)?)/);
  return match ? match[1] : null;
};

const obtenerCapitulosDescargas = (mangaId) =>
  dbAll(
    `SELECT id,
            nombre_capitulo,
            enlace,
            numero_capitulo,
            orden,
            descargado,
            fecha_descarga
     FROM descargas
     WHERE manga_id = ?
     ORDER BY orden ASC, id ASC`,
    [mangaId]
  );

const mapearCapitulosDescarga = (capitulos) =>
  capitulos.map((cap, index) => ({
    id: cap.id,
    nombre: cap.nombre_capitulo,
    enlace: cap.enlace,
    numero: cap.numero_capitulo,
    descargado: cap.descargado === 1,
    fecha_descarga: cap.fecha_descarga,
    orden: Number.isFinite(cap.orden) ? cap.orden : index,
  }));

async function obtenerCapitulosDesdeWeb(url) {
  try {
    const response = await axios.get(url);
    const $ = cheerio.load(response.data);
    const capitulos = [];
    $('.col-xs-12.chapter h4 a').each((index, element) => {
      const enlaceNodo = $(element);
      const nombre = enlaceNodo.text().trim();
      const href = enlaceNodo.attr('href');
      if (!nombre || !href) return;
      capitulos.push({
        nombre,
        enlace: resolverUrlRelativa(url, href),
        numero: extraerNumeroCapitulo(nombre),
        orden: index,
      });
    });
    return capitulos;
  } catch (error) {
    console.error('Error al obtener capítulos completos:', error);
    return [];
  }
}

async function prepararDescargasParaManga(mangaId, url) {
  let capitulos = await obtenerCapitulosDescargas(mangaId);

  if (capitulos.length > 0) {
    return capitulos;
  }

  const capitulosWeb = await obtenerCapitulosDesdeWeb(url);
  if (!capitulosWeb.length) {
    return [];
  }

  const fechaRegistro = new Date().toISOString();
  for (const cap of capitulosWeb) {
    try {
      await dbRun(
        `INSERT INTO descargas (
           manga_id,
           nombre_capitulo,
           enlace,
           numero_capitulo,
           orden,
           fecha_registro
         ) VALUES (?, ?, ?, ?, ?, ?)
         ON CONFLICT(manga_id, nombre_capitulo)
         DO UPDATE SET
           enlace = excluded.enlace,
           numero_capitulo = excluded.numero_capitulo,
           orden = excluded.orden`,
        [
          mangaId,
          cap.nombre,
          cap.enlace,
          cap.numero,
          cap.orden,
          fechaRegistro,
        ]
      );
    } catch (error) {
      console.error(
        `No se pudo registrar el capítulo "${cap.nombre}" para el manga ${mangaId}:`,
        error
      );
    }
  }

  capitulos = await obtenerCapitulosDescargas(mangaId);

  return capitulos;
}

// Eliminar un manga por ID
app.delete('/mangas/:id', (req, res) => {
  const { id } = req.params;

  db.run('DELETE FROM manga WHERE id = ?', [id], function (err) {
    if (err) {
      return res.status(500).json({ error: 'Error al eliminar el manga' });
    }

    if (this.changes === 0) {
      return res.status(404).json({ error: 'Manga no encontrado' });
    }

    res.json({ mensaje: 'Manga eliminado exitosamente' });
  });
});

// Ruta para actualizar todos los mangas
app.post('/mangas/actualizar-todos', async (req, res) => {
  try {
    // Obtener todos los mangas de la base de datos
    db.all('SELECT id FROM manga', async (err, mangas) => {
      if (err)
        return res.status(500).json({ error: 'Error al obtener los mangas' });

      const resultados = [];
      const novedades = [];

      // Recorrer todos los mangas y actualizarlos uno por uno
      for (const manga of mangas) {
        try {
          const resultado = await actualizarMangaPorId(manga.id);
          resultados.push({ id: manga.id, ...resultado });
          if (resultado.nuevo) {
            novedades.push(manga.id);
          }
        } catch (error) {
          console.error(
            `Error actualizando manga con ID ${manga.id}: ${error.message}`
          );
        }
      }

      // Devolver los mangas actualizados
      res.json({
        mensaje:
          novedades.length > 0
            ? `Actualización completada. Nuevos capítulos en los mangas con ID: ${novedades.join(
                ', '
              )}`
            : 'Actualización completada sin nuevos capítulos',
        resultados,
      });
    });
  } catch (error) {
    res.status(500).json({ error: 'Error al actualizar los mangas' });
  }
});

app.put('/mangas/:id/url', async (req, res) => {
  const { id } = req.params;
  let { url } = req.body || {};

  if (!id) {
    return res.status(400).json({ error: 'Falta el ID del manga' });
  }

  if (!url) {
    return res.status(400).json({ error: 'La nueva URL es requerida' });
  }

  try {
    const nuevaUrl = String(url).trim();
    if (!nuevaUrl) {
      return res
        .status(400)
        .json({ error: 'La nueva URL no puede estar vacía' });
    }

    const mangaExistente = await dbGet(
      'SELECT id, url FROM manga WHERE id = ?',
      [id]
    );

    if (!mangaExistente) {
      return res.status(404).json({ error: 'Manga no encontrado' });
    }

    const urlDuplicada = await dbGet(
      'SELECT id FROM manga WHERE url = ? AND id != ?',
      [nuevaUrl, id]
    );

    if (urlDuplicada) {
      return res.status(409).json({
        error: 'La URL ya está asociada a otro manga',
      });
    }

    const resultado = await dbRun(
      'UPDATE manga SET url = ? WHERE id = ?',
      [nuevaUrl, id]
    );

    if (!resultado || resultado.changes === 0) {
      return res.status(500).json({
        error: 'No se pudo actualizar la URL del manga',
      });
    }

    const mangaActualizado = await obtenerMangaConProgreso(id);
    res.json({
      mensaje: 'URL actualizada correctamente',
      manga: mangaActualizado,
    });
  } catch (error) {
    console.error('Error al actualizar URL:', error);
    res
      .status(500)
      .json({ error: 'Error al actualizar la URL del manga' });
  }
});

const construirResumenDescargas = (capitulos) => {
  const total = capitulos.length;
  const descargados = capitulos.filter((cap) => cap.descargado === 1).length;
  const pendientes = total - descargados;

  const ultimoDescargado =
    capitulos
      .filter((cap) => cap.descargado === 1)
      .sort((a, b) => {
        const fechaA = a.fecha_descarga
          ? new Date(a.fecha_descarga).getTime()
          : 0;
        const fechaB = b.fecha_descarga
          ? new Date(b.fecha_descarga).getTime()
          : 0;
        if (fechaA !== fechaB) return fechaB - fechaA;

        const numA = parseFloat(a.numero_capitulo);
        const numB = parseFloat(b.numero_capitulo);
        if (!Number.isNaN(numA) && !Number.isNaN(numB)) {
          return numB - numA;
        }

        const ordenA = Number.isFinite(a.orden) ? a.orden : 0;
        const ordenB = Number.isFinite(b.orden) ? b.orden : 0;
        return ordenB - ordenA;
      })[0] || null;

  return {
    total,
    descargados,
    pendientes,
    ultimo_descargado: ultimoDescargado
      ? ultimoDescargado.nombre_capitulo
      : null,
  };
};

app.get('/manga/:id/descargas', async (req, res) => {
  const { id } = req.params;
  if (!id) return res.status(400).json({ error: 'Falta el ID del manga' });

  try {
    const manga = await dbGet(
      `SELECT m.id,
              m.nombre,
              m.url,
              m.ultimo_capitulo,
              COALESCE(p.capitulo_actual, m.ultimo_capitulo, '0') AS capitulo_actual
       FROM manga m
       LEFT JOIN progreso_manga p ON m.id = p.manga_id
       WHERE m.id = ?`,
      [id]
    );

    if (!manga) {
      return res.status(404).json({ error: 'Manga no encontrado' });
    }

    const capitulos = await prepararDescargasParaManga(manga.id, manga.url);

    const resumen = construirResumenDescargas(capitulos);

    res.json({
      manga: {
        id: manga.id,
        nombre: manga.nombre,
        url: manga.url,
        capitulo_actual: manga.capitulo_actual,
        ultimo_capitulo: manga.ultimo_capitulo,
      },
      resumen,
      capitulos: mapearCapitulosDescarga(capitulos),
    });
  } catch (error) {
    console.error('Error al obtener descargas:', error);
    res.status(500).json({ error: 'Error al obtener las descargas' });
  }
});

app.patch('/descargas/:id', async (req, res) => {
  const { id } = req.params;
  const { descargado } = req.body || {};

  if (!id) return res.status(400).json({ error: 'Falta el ID del capítulo' });
  if (typeof descargado !== 'boolean') {
    return res
      .status(400)
      .json({ error: 'El estado descargado debe ser booleano' });
  }

  try {
    const capitulo = await dbGet(
      `SELECT id, manga_id FROM descargas WHERE id = ?`,
      [id]
    );
    if (!capitulo) {
      return res.status(404).json({ error: 'Capítulo no encontrado' });
    }

    const fechaDescarga = descargado ? new Date().toISOString() : null;
    await dbRun(
      `UPDATE descargas
       SET descargado = ?, fecha_descarga = ?
       WHERE id = ?`,
      [descargado ? 1 : 0, fechaDescarga, id]
    );

    const capitulos = await obtenerCapitulosDescargas(capitulo.manga_id);

    res.json({
      actualizado: true,
      resumen: construirResumenDescargas(capitulos),
    });
  } catch (error) {
    console.error('Error al actualizar descarga:', error);
    res
      .status(500)
      .json({ error: 'Error al actualizar el estado de la descarga' });
  }
});

app.post('/manga/:id/descargas/marcar-todos', async (req, res) => {
  const { id } = req.params;
  if (!id) return res.status(400).json({ error: 'Falta el ID del manga' });

  try {
    const manga = await dbGet(
      `SELECT id, url
       FROM manga
       WHERE id = ?`,
      [id]
    );

    if (!manga) {
      return res.status(404).json({ error: 'Manga no encontrado' });
    }

    let capitulos = await prepararDescargasParaManga(manga.id, manga.url);

    if (!capitulos.length) {
      return res.json({
        actualizado: false,
        resumen: construirResumenDescargas([]),
        capitulos: [],
        mensaje:
          'No se encontraron capítulos para este manga durante la sincronización.',
      });
    }

    const fechaDescarga = new Date().toISOString();
    await dbRun(
      `UPDATE descargas
       SET descargado = 1,
           fecha_descarga = CASE
             WHEN fecha_descarga IS NULL THEN ?
             ELSE fecha_descarga
           END
       WHERE manga_id = ?`,
      [fechaDescarga, manga.id]
    );

    capitulos = await obtenerCapitulosDescargas(manga.id);

    res.json({
      actualizado: true,
      resumen: construirResumenDescargas(capitulos),
      capitulos: mapearCapitulosDescarga(capitulos),
    });
  } catch (error) {
    console.error('Error al marcar descargas:', error);
    res
      .status(500)
      .json({ error: 'Error al marcar todos los capítulos como descargados' });
  }
});

app.listen(PORT, () =>
  console.log(`Servidor corriendo en http://localhost:${PORT}`)
);
