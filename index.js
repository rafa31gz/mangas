const express = require('express');
const fs = require('fs');
const axios = require('axios');
const cheerio = require('cheerio');
const sqlite3 = require('sqlite3').verbose();
const app = express();
const PORT = 5000;
const DB_FILE = 'manga.db';

app.use(express.json());
app.use(express.static('public'));

const db = new sqlite3.Database(DB_FILE, (err) => {
  if (err) console.error(err.message);
  else console.log('Conectado a la base de datos SQLite');
});

// Crear tabla si no existe
db.run(`CREATE TABLE IF NOT EXISTS manga (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT UNIQUE,
    url TEXT,
    ultimo_capitulo TEXT,
    fecha_consulta TEXT
)`);

// Agregar tabla para el progreso del manga
db.run(`CREATE TABLE IF NOT EXISTS progreso_manga (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manga_id INTEGER UNIQUE,
    capitulo_actual TEXT,
    FOREIGN KEY (manga_id) REFERENCES manga(id)
)`);

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
        SELECT m.id, m.nombre, m.url, m.ultimo_capitulo, m.fecha_consulta, 
               p.capitulo_actual 
        FROM manga m 
        LEFT JOIN progreso_manga p ON m.id = p.manga_id`;

  db.all(query, [], (err, rows) => {
    if (err)
      return res.status(500).json({ error: 'Error en la base de datos' });
    res.json(rows);
  });
});

// Agregar un nuevo manga con URL
app.post('/mangas', (req, res) => {
  const { nombre, url } = req.body;
  if (!nombre || !url)
    return res.status(400).json({ error: 'Nombre y URL son requeridos' });

  db.run(
    'INSERT INTO manga (nombre, url) VALUES (?, ?)',
    [nombre, url],
    (err) => {
      if (err) return res.status(500).json({ error: 'Error al agregar manga' });
      res.json({ mensaje: 'Manga agregado exitosamente' });
    }
  );
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

        const fechaActual = new Date().toLocaleString('es-MX');

        db.get(
          `SELECT m.id, m.nombre, m.url, m.ultimo_capitulo, m.fecha_consulta, 
                  p.capitulo_actual, m.fecha_nuevo_capitulo 
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

            let hayNuevo = false;

            if (row.ultimo_capitulo !== nuevoCapitulo) {
              const fechaNuevoCapitulo = row.fecha_nuevo_capitulo
                ? new Date(row.fecha_nuevo_capitulo)
                : null;
              const diferencia = fechaNuevoCapitulo
                ? (new Date() - fechaNuevoCapitulo) / (1000 * 60 * 60 * 24)
                : Infinity;

              if (diferencia > 1 || !fechaNuevoCapitulo) {
                hayNuevo = true;
                db.run(
                  `UPDATE manga 
                   SET ultimo_capitulo = ?, fecha_consulta = ?, fecha_nuevo_capitulo = ? 
                   WHERE id = ?`,
                  [nuevoCapitulo, fechaActual, fechaActual, id],
                  (err) => {
                    if (err) {
                      console.error('Error al actualizar el manga:', err);
                      return reject({ error: 'Error al actualizar datos' });
                    }
                  }
                );
              }
            }

            resolve({
              mensaje: hayNuevo
                ? 'Nuevo capítulo disponible'
                : 'No hay capítulos nuevos',
              ultimo_capitulo: nuevoCapitulo,
              capitulo_actual: row.capitulo_actual || 0,
              fecha: fechaActual,
              nuevo: hayNuevo,
            });
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

      let actualizaciones = [];

      // Recorrer todos los mangas y actualizarlos uno por uno
      for (const manga of mangas) {
        try {
          const resultado = await actualizarMangaPorId(manga.id);
          if (resultado.nuevo) {
            actualizaciones.push(manga.id); // Guardar ID de mangas que han sido actualizados
          }
        } catch (error) {
          console.error(
            `Error actualizando manga con ID ${manga.id}: ${error.message}`
          );
        }
      }

      // Devolver los mangas actualizados
      res.json({
        mensaje: `Actualización completada para los mangas con ID: ${actualizaciones.join(
          ', '
        )}`,
      });
    });
  } catch (error) {
    res.status(500).json({ error: 'Error al actualizar los mangas' });
  }
});

app.listen(PORT, () =>
  console.log(`Servidor corriendo en http://localhost:${PORT}`)
);