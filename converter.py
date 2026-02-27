from PIL import Image
import datetime
import requests
import os
import glob
import json
import base64
import io

# --- Funciones de Utilidad ---

def calcular_edad_exacta(fecha_nacimiento_str):
    """
    Calcula la edad exacta en años, meses y días desde una fecha de nacimiento.
    Formato de fecha_nacimiento_str: 'YYYY-MM-DD'
    """
    fecha_nacimiento = datetime.datetime.strptime(fecha_nacimiento_str, '%Y-%m-%d').date()
    today = datetime.date.today()
    
    años = today.year - fecha_nacimiento.year
    if (today.month, today.day) < (fecha_nacimiento.month, fecha_nacimiento.day):
        años -= 1
    
    fecha_aniversario = fecha_nacimiento.replace(year=fecha_nacimiento.year + años)
    
    if today >= fecha_aniversario:
        meses = today.month - fecha_aniversario.month
        dias = today.day - fecha_aniversario.day
        
        if dias < 0:
            last_day_of_prev_month = (today.replace(day=1) - datetime.timedelta(days=1)).day
            dias = last_day_of_prev_month + dias
            meses -= 1
            
            if meses < 0:
                meses += 12
    else:
        fecha_aniversario_pasado = fecha_nacimiento.replace(year=fecha_nacimiento.year + años)
        
        meses = today.month - fecha_aniversario_pasado.month
        dias = today.day - fecha_aniversario_pasado.day

        if dias < 0:
            last_day_of_prev_month = (today.replace(day=1) - datetime.timedelta(days=1)).day
            dias = last_day_of_prev_month + dias
            meses -= 1
        
        if meses < 0:
            meses += 12

    return f"{años} años, {meses} meses, {dias} días"

def convertir_imagen_a_ascii(ruta_o_base64, ancho_salida=100):
    """
    Convierte una imagen (ruta de archivo o string base64) a arte ASCII.
    """
    try:
        if ruta_o_base64.startswith("data:image") or len(ruta_o_base64) > 500: # Probable Base64
            if "," in ruta_o_base64:
                ruta_o_base64 = ruta_o_base64.split(",")[1]
            img_data = base64.b64decode(ruta_o_base64)
            imagen = Image.open(io.BytesIO(img_data))
        else:
            imagen = Image.open(ruta_o_base64)
    except Exception as e:
        print(f"Error al cargar la imagen: {e}")
        return None
    except FileNotFoundError:
        print(f"Error: La imagen en la ruta '{ruta_o_base64}' no fue encontrada.")
        return None
    except Exception as e:
        print(f"Error al abrir la imagen: {e}")
        return None

    imagen = imagen.convert("L") #Convierte la imagen a escala de grises. | L = Luminosidad

    ancho_original, alto_original = imagen.size
    relacion_aspecto = alto_original / ancho_original
    alto_salida = int(ancho_salida * relacion_aspecto * 0.55) 
    imagen = imagen.resize((ancho_salida, alto_salida))

    ascii_chars = "#W$@%*+=-. " # Puedes cambiar valores para mas detalles ASCII Art, izquierda a derecha | claro a oscuro

    pixels = imagen.getdata()
    ascii_art = ""
    for pixel_value in pixels:
        index = int(pixel_value / 255 * (len(ascii_chars) - 1))
        ascii_art += ascii_chars[index]

    ascii_lines = [ascii_art[i:i + ancho_salida] for i in range(0, len(ascii_art), ancho_salida)]
    
    return "\n".join(ascii_lines)

# --- FUNCIONES PARA OBTENER DATOS DE GITHUB ---
def obtener_datos_github_graphql(username, token):
    """
    Obtiene estadísticas precisas de GitHub usando GraphQL, incluyendo LOC dinámico.
    """
    query = """
    query($login: String!) {
      user(login: $login) {
        followers { totalCount }
        repositories(first: 30, ownerAffiliations: OWNER, orderBy: {field: PUSHED_AT, direction: DESC}) {
          totalCount
          nodes {
            stargazers { totalCount }
            forkCount
            defaultBranchRef {
              target {
                ... on Commit {
                  history(first: 100) {
                    nodes {
                      additions
                      deletions
                      author {
                        user {
                          login
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        contributionsCollection {
          contributionCalendar {
            totalContributions
          }
        }
      }
    }
    """
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = requests.post("https://api.github.com/graphql", json={"query": query, "variables": {"login": username}}, headers=headers)
        response.raise_for_status()
        res_json = response.json()
        if "data" not in res_json or res_json["data"]["user"] is None:
            raise Exception(f"Error en respuesta GraphQL: {res_json}")
            
        data = res_json["data"]["user"]
        repos = data["repositories"]["nodes"]
        
        total_additions = 0
        total_deletions = 0
        
        for repo in repos:
            if repo["defaultBranchRef"] and repo["defaultBranchRef"]["target"]:
                commits = repo["defaultBranchRef"]["target"]["history"]["nodes"]
                for commit in commits:
                    # Solo contar si el autor es el usuario (login coincide)
                    if commit["author"]["user"] and commit["author"]["user"]["login"].lower() == username.lower():
                        total_additions += commit["additions"]
                        total_deletions += commit["deletions"]

        net_loc = total_additions - total_deletions
        loc_formatted = f"{net_loc:,} (+{total_additions:,}, -{total_deletions:,})"

        stats = {
            "total_repos": data["repositories"]["totalCount"],
            "total_stars": sum(r["stargazers"]["totalCount"] for r in repos if "stargazers" in r),
            "total_forks": sum(r["forkCount"] for r in repos if "forkCount" in r),
            "total_followers": data["followers"]["totalCount"],
            "total_commits": data["contributionsCollection"]["contributionCalendar"]["totalContributions"],
            "dynamic_loc": loc_formatted
        }
        return stats
    except Exception as e:
        print(f"Error en GraphQL: {e}. Usando valores por defecto.")
        return {
            "total_repos": 0, "total_stars": 0, "total_forks": 0, 
            "total_followers": 0, "total_commits": 0, "dynamic_loc": "0"
        }

# --- FUNCIONES PARA OBTENER DATOS DE GITHUB (LEGACY REST) ---

# --- FUNCION PRINCIPAL DE GENERACION SVG ---

def generar_svg_con_info(ascii_art_string, info_sections, output_filename="readme_profile.svg", 
                         bg_color="#161b22", text_color="#c9d1d9", 
                         key_color="#ffa657", value_color="#a5d6ff", font_size=16,
                         border_color="#444c56", border_width=2, border_radius=10):
    """
    Generates an SVG file with ASCII art on the left and profile data on the right.
    """
    ascii_lines = ascii_art_string.split('\n')
    
    char_width_px = 9.6 
    line_height_factor = 1.2 

    # --- SVG Dimensions ---
    ascii_max_width_chars = max(len(line) for line in ascii_lines)
    ascii_panel_width = int(ascii_max_width_chars * char_width_px) + 0
    
    info_panel_base_width = 525 
    
    info_total_lines = 0
    if info_sections and info_sections[0].get("title") == "username_header":
        info_total_lines += 2 
        
    for section in info_sections:
        if section.get("title") and section["title"] != "username_header":
            info_total_lines += 1 
        info_total_lines += len(section.get('items', []))
        if section.get('extra_line_after', False): 
            info_total_lines += 1 

    info_height = info_total_lines * font_size * line_height_factor
    
    min_required_svg_height = int(max(len(ascii_lines) * font_size * line_height_factor, info_height)) + 80 

    svg_width = ascii_panel_width + info_panel_base_width + 30 

    svg_height = max(int(len(ascii_lines) * font_size * line_height_factor) + 0, info_height + 80)


    icon_map = {
        "Nombre": "👤", 
        "Edad": "🎂", "Ubicación": "📍", "Intereses": "💡",
        "Stack": "💻", 
        "Lenguajes de Programación": "🧠", "Tecnologías Web": "🌐", 
        "Bases de Datos": "💾", "Herramientas DevOps": "🛠️",
        "Hobbies": "🎮", 
        "Email": "📧", "LinkedIn": "🔗", 
        "Total Repositorios": "📦", "Estrellas Totales": "⭐", 
        "Forks Totales": "🍴", "Total Commits": "⚡", 
        "Seguidores": "👥", "Líneas de Código (LOC)": "📈",
    }

    svg_content = f"""<?xml version='1.0' encoding='UTF-8'?>
<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" width="{svg_width}px" height="{svg_height}px" font-size="{font_size}px">
<style>
@font-face {{
  src: local('Consolas'), local('Consolas Bold');
  font-family: 'ConsolasFallback';
  font-display: swap;
  -webkit-size-adjust: 109%;
  size-adjust: 109%;
}}
.key {{fill: {key_color};}}
.value {{fill: {value_color};}}
.header-line {{fill: {text_color};}}
.section-title {{fill: {key_color}; font-weight: bold;}}
text, tspan {{white-space: pre;}}
</style>
<rect width="100%" height="100%" fill="{bg_color}" stroke="{border_color}" stroke-width="{border_width}" rx="{border_radius}" ry="{border_radius}"/>

<g id="ascii-panel">
<text fill="{text_color}">
"""
    ascii_panel_height = len(ascii_lines) * font_size * line_height_factor
    ascii_start_y = (svg_height - ascii_panel_height) / 2 + font_size 

    for i, line in enumerate(ascii_lines):
        x_pos = 15 + (ascii_panel_width - (len(line) * char_width_px)) / 2 
        y_pos = ascii_start_y + (i * font_size * line_height_factor)
        svg_content += f'<tspan x="{x_pos}" y="{y_pos}">{line}</tspan>\n'

    svg_content += """</text>
</g>
<g id="info-panel">
"""
    info_panel_height_actual = info_total_lines * font_size * line_height_factor 
    info_panel_start_y = (svg_height - info_panel_height_actual) / 2 + font_size 


    info_x_start = ascii_panel_width + 15
    current_y = info_panel_start_y 

    guiones_longitud_dinamica = int((info_panel_base_width - (info_x_start - ascii_panel_width)) / char_width_px) - 2 


    svg_content += f"""<text x="{info_x_start}" y="{info_panel_start_y}" fill="{text_color}">"""

    for section in info_sections:
        if section.get("title") == "username_header":
            username_text = section["username"]

            remaining_space_for_username = guiones_longitud_dinamica - len(username_text)
            
            if remaining_space_for_username < 0:
                remaining_space_for_username = 0

            dashes_left_username = remaining_space_for_username // 2
            dashes_right_username = remaining_space_for_username - dashes_left_username 
            
            centered_username_line = f"{'-' * dashes_left_username}{username_text}{'-' * dashes_right_username}"
            
            if len(centered_username_line) > guiones_longitud_dinamica:
                centered_username_line = centered_username_line[:guiones_longitud_dinamica]

            svg_content += f'<tspan x="{info_x_start}" y="{current_y}">{centered_username_line}</tspan>\n'
            current_y += font_size * line_height_factor
            
            svg_content += f'<tspan x="{info_x_start}" y="{current_y}">{"-" * guiones_longitud_dinamica}</tspan>\n' 
            current_y += font_size * line_height_factor * 1.2 
        elif section.get("title"):
            title_text_content = f"- {section['title']}"
            
            dashes_needed = guiones_longitud_dinamica - len(title_text_content)
            
            if dashes_needed < 0:
                dashes_needed = 0
            
            dashes_content = '-' * dashes_needed

            svg_content += f'<tspan x="{info_x_start}" y="{current_y}" class="section-title">{title_text_content}</tspan>'
            
            dashes_start_x = info_x_start + (len(title_text_content) * char_width_px)
            
            if dashes_start_x + (len(dashes_content) * char_width_px) > (info_x_start + info_panel_base_width - 30): 
                max_dashes_chars = int(((info_x_start + info_panel_base_width - 30) - dashes_start_x) / char_width_px)
                if max_dashes_chars < 0: max_dashes_chars = 0
                dashes_content = '-' * max_dashes_chars

            svg_content += f'<tspan x="{dashes_start_x}" y="{current_y}" fill="{text_color}">{dashes_content}</tspan>\n'
            
            current_y += font_size * line_height_factor * 1.2 

        for item_key, item_value in section.get('items', []):
            icon = icon_map.get(item_key, "") + " " 
            
            if item_key in ["Stack", "Lenguajes de Programación", "Tecnologías Web", 
                             "Bases de Datos", "Herramientas DevOps", "Hobbies",
                             "Email", "LinkedIn", "Twitter", "Discord"]: 
                svg_content += f'<tspan x="{info_x_start}" y="{current_y}" class="key">{icon}{item_key}: </tspan>'
                svg_content += f'<tspan class="value">{str(item_value)}</tspan>\n'
            elif item_key == "Líneas de Código (LOC)":
                parts = str(item_value).split(" ", 1) 
                total_loc = parts[0]
                details_loc = parts[1] if len(parts) > 1 else ""

                svg_content += f'<tspan x="{info_x_start}" y="{current_y}" class="key">{icon}{item_key}: </tspan>'
                svg_content += f'<tspan class="value">{total_loc}</tspan>'
                
                if details_loc:
                    add_part = ""
                    del_part = ""
                    
                    details_stripped = details_loc.replace('(', '').replace(')', '').strip()
                    parts_inner = [p.strip() for p in details_stripped.split(',')]
                    
                    for p in parts_inner:
                        if p.startswith('+'):
                            add_part = p
                        elif p.startswith('-'):
                            del_part = p

                    svg_content += f'<tspan class="value"> (</tspan>'
                    if add_part:
                        svg_content += f'<tspan fill="#3fb950">{add_part}</tspan>'
                    if add_part and del_part:
                        svg_content += f'<tspan class="value">,</tspan><tspan> </tspan>'
                    if del_part:
                        svg_content += f'<tspan fill="#f85149">{del_part}</tspan>'
                    svg_content += f'<tspan class="value">)</tspan>'

                svg_content += '\n'
            else: # For short, standard key-value pairs with dots
                key_str = f"{icon}{item_key}: "
                value_str = str(item_value)

                key_char_len = len(key_str)
                value_char_len = len(value_str)
                
                available_chars_for_line = guiones_longitud_dinamica 
                
                dots_char_count = max(0, available_chars_for_line - key_char_len - value_char_len - 1) 
                
                dots_content = "." * dots_char_count

                svg_content += f'<tspan x="{info_x_start}" y="{current_y}" class="key">{key_str}</tspan>'
                
                dots_x_pos = info_x_start + (key_char_len * char_width_px)
                svg_content += f'<tspan x="{dots_x_pos}" y="{current_y}" fill="{text_color}">{dots_content}</tspan>'
                
                value_x_pos = dots_x_pos + (dots_char_count * char_width_px) + (char_width_px * 1) 
                svg_content += f'<tspan x="{value_x_pos}" y="{current_y}" class="value">{value_str}</tspan>\n'
            
            current_y += font_size * line_height_factor

        if section.get('extra_line_after', False):
            current_y += font_size * line_height_factor * 0.5 

    svg_content += """</text>
</g> </svg>"""

    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(svg_content)

# --- SCRIPT USAGE ---
if __name__ == "__main__":
    # Cargar configuración desde JSON
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print("Error: No se encontró config.json")
        exit(1)

    tu_github_username = config["github_username"]
    datos_perfil = config["profile_data"]

    # Determinar fuente de la imagen (Prioridad: Secret -> Archivo local)
    ruta_o_base64 = os.getenv("PROFILE_IMAGE_BASE64", "me.jpg")
    ancho_deseado_ascii = 50

    # Obtener el token de GitHub
    github_token = os.getenv("GITHUB_TOKEN") 
    if not github_token:
        print("Advertencia: No se encontró GITHUB_TOKEN. Usando estadísticas manuales si es posible.")
        github_stats = {
            "total_repos": 0, "total_stars": 0, "total_forks": 0, 
            "total_followers": 0, "total_commits": 0, "dynamic_loc": "0"
        }
    else:
        # Obtener los datos de GitHub via GraphQL
        github_stats = obtener_datos_github_graphql(tu_github_username, github_token)

    mis_datos_secciones = [
        {
            "title": "username_header",
            "username": datos_perfil["username_display"],
            "items": [
                ("Edad", calcular_edad_exacta(datos_perfil["birth_date"])),
                ("Ubicación", datos_perfil["location"]),
                ("Intereses", datos_perfil["interests"]),
            ],
            "extra_line_after": True
        },
        {
            "title": "Stack",
            "items": [
                ("Stack", datos_perfil["stack"]),
                ("Lenguajes de Programación", datos_perfil["languages"]),
                ("Tecnologías Web", datos_perfil["web_technologies"]), 
                ("Bases de Datos", datos_perfil["databases"]), 
                ("Herramientas DevOps", datos_perfil["devops_tools"]), 
            ],
            "extra_line_after": True
        },
        {
            "title": "Hobbies",
            "items": [
                ("Hobbies", datos_perfil["hobbies"]),
            ],
            "extra_line_after": True
        },
        {
            "title": "Contacto",
            "items": [
                ("Email", datos_perfil["email"]),
                ("LinkedIn", datos_perfil["linkedin"]),
            ],
            "extra_line_after": True
        }
    ]

    # Añadir estadísticas si tenemos token
    if github_token:
        mis_datos_secciones.append({
            "title": "GitHub Stats",
            "items": [
                ("Total Repositorios", github_stats["total_repos"]),
                ("Estrellas Totales", github_stats["total_stars"]),
                ("Forks Totales", github_stats["total_forks"]),
                ("Total Commits", github_stats["total_commits"]),
                ("Seguidores", github_stats["total_followers"]),
                ("Líneas de Código (LOC)", github_stats["dynamic_loc"]), 
            ],
            "extra_line_after": False
        })

    # --- CONFIGURACIÓN DE COLORES PARA TEMAS ---
    temas = {
        "dark": {
            "bg_color": "#161b22",
            "text_color": "#c9d1d9",
            "key_color": "#ffa657",
            "value_color": "#a5d6ff",
            "border_color": "#444c56",
            "filename": "dark_mode.svg"
        },
        "light": {
            "bg_color": "#ffffff",
            "text_color": "#24292f",
            "key_color": "#af5e14",
            "value_color": "#0969da",
            "border_color": "#d0d7de",
            "filename": "light_mode.svg"
        }
    }
    
    border_width = 2 
    border_radius = 10 
    
    print(f"Generando arte ASCII para el perfil...")
    ascii_result = convertir_imagen_a_ascii(ruta_o_base64, ancho_salida=ancho_deseado_ascii)

    if ascii_result:
        for nombre_tema, colores in temas.items():
            print(f"Generando SVG para tema {nombre_tema} ({colores['filename']})...")
            generar_svg_con_info(ascii_result,
                                 mis_datos_secciones,
                                 output_filename=colores['filename'],
                                 bg_color=colores['bg_color'],
                                 text_color=colores['text_color'],
                                 key_color=colores['key_color'],
                                 value_color=colores['value_color'],
                                 border_color=colores['border_color'],
                                 border_width=border_width,
                                 border_radius=border_radius
                                 )
        
        print("¡Archivos SVG generados con éxito!")

        # 2. Actualizar el archivo README.md para que use <picture> (Tema dinámico)
        readme_content = f"""<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./{temas['dark']['filename']}">
    <img alt="GitHub Profile README" src="./{temas['light']['filename']}">
  </picture>
</div>
"""
        with open("README.md", "w", encoding="utf-8") as f:
            f.write(readme_content)

        print(f"¡README.md actualizado con soporte para temas claro/oscuro!")
        print(f"Ahora puedes hacer commit de: {temas['dark']['filename']}, {temas['light']['filename']}, 'config.json' y 'README.md'")

    else:
        print("\nNo se pudo generar el arte ASCII. Revisa la configuración de imagen.")
