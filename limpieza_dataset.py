import os
import re
import json
import pandas as pd
import numpy as np

# ==========================================
# 1. CONFIGURACIÓN DE RUTAS Y CODIFICACIÓN
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
INPUT_CSV = os.path.join(BASE_DIR, 'DOHMH_MenuStat_(Historical)_20261016.csv')
OUTPUT_DIR = os.path.join(BASE_DIR, 'data')
OUTPUT_JSON = os.path.join(OUTPUT_DIR, 'bebidas_limpias.json')

# Crear la carpeta 'data' si no existe
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==========================================
# 2. FUNCIONES DE EXTRACCIÓN Y LIMPIEZA
# ==========================================

def detectar_crema(texto: str) -> bool:
    """
    Determina si la bebida lleva crema batida (True) o no (False).
    Evalúa primero las negaciones explícitas para evitar falsos positivos.
    """
    if not isinstance(texto, str):
        return False
    
    # 1. Negaciones explícitas ("w/o whip", "without whipped cream", "no whip")
    patron_sin_crema = r'\b(?:w/o\s*whip(?:ped)?(?:\s*cream)?|without\s*whip(?:ped)?(?:\s*cream)?|no\s*whip(?:ped)?(?:\s*cream)?|sin\s*crema)\b'
    if re.search(patron_sin_crema, texto, flags=re.IGNORECASE):
        return False
    
    # 2. Afirmaciones explícitas ("w/ whip", "with whipped cream", "whipped cream", "whip")
    patron_con_crema = r'\b(?:w/\s*whip(?:ped)?(?:\s*cream)?|with\s*whip(?:ped)?(?:\s*cream)?|whipped\s*cream|whip\s*cream|whip)\b'
    if re.search(patron_con_crema, texto, flags=re.IGNORECASE):
        return True
    
    return False


def extraer_tipo_leche(texto: str) -> str:
    """
    Extrae y estandariza el tipo de leche a partir del nombre y la descripción.
    """
    if not isinstance(texto, str):
        return 'Sin leche'
    
    patrones_leche = [
        (r'\b(?:non[- ]?fat\s*milk|skim\s*milk|fat[- ]?free\s*milk|non[- ]?fat)\b', 'Nonfat Milk'),
        (r'\b(?:2%\s*milk|reduced[- ]?fat\s*milk|2%)\b', '2% Milk'),
        (r'\b(?:1%\s*milk|low[- ]?fat\s*milk|1%)\b', '1% Milk'),
        (r'\b(?:whole\s*milk|whole)\b', 'Whole Milk'),
        (r'\b(?:soy\s*milk|soymilk|soy)\b', 'Soy Milk'),
        (r'\b(?:almond\s*milk|almondmilk|almond)\b', 'Almond Milk'),
        (r'\b(?:coconut\s*milk|coconutmilk)\b', 'Coconut Milk'),
        (r'\b(?:oat\s*milk|oatmilk)\b', 'Oat Milk'),
        (r'\b(?:breve|half\s*(?:&|and)\s*half)\b', 'Breve (Half & Half)'),
        (r'\b(?:with\s+milk|whole/regular\s+milk)\b', 'Regular Milk')
    ]
    
    for patron, etiqueta in patrones_leche:
        if re.search(patron, texto, flags=re.IGNORECASE):
            return etiqueta
            
    return 'Sin leche'


def mapear_oz_a_tamano(val) -> str | None:
    """Mapea las onzas a su denominación oficial de tamaño en Starbucks."""
    try:
        oz = float(str(val).replace(',', '.'))
    except (ValueError, TypeError):
        return None

    equivalencias = {
        8.0: 'Short',
        12.0: 'Tall',
        16.0: 'Grande',
        20.0: 'Venti',
        24.0: 'Venti',
        30.0: 'Trenta',
        31.0: 'Trenta',
        1.0: 'Solo',
        2.0: 'Doppio',
        3.0: 'Triple',
        4.0: 'Quad'
    }
    return equivalencias.get(oz)


def extraer_tamano_vaso(fila) -> str:
    """Extrae el tamaño del vaso estandarizando nombres y volúmenes en onzas."""
    texto_principal = f"{fila.get('Item_Name', '')} {fila.get('Serving_Size_household', '')} {fila.get('Item_Description', '')}"
    
    # 1. Buscar nombres canónicos directos
    patrones_tamano = [
        (r'\btrenta\b', 'Trenta'),
        (r'\bventi\b', 'Venti'),
        (r'\bgrande\b', 'Grande'),
        (r'\btall\b', 'Tall'),
        (r'\bshort\b', 'Short'),
        (r'\b(?:kids\'?|child\'?s?|child|mini)\b', 'Kids / Mini'),
        (r'\b(?:extra\s*large|x-large|xl)\b', 'Extra Large'),
        (r'\blarge\b', 'Large'),
        (r'\bmedium\b', 'Medium'),
        (r'\bsmall\b', 'Small'),
        (r'\bsingle\b|\bsolo\b', 'Solo'),
        (r'\bdouble\b|\bdoppio\b', 'Doppio'),
        (r'\btriple\b', 'Triple'),
        (r'\bquad\b', 'Quad'),
        (r'\bregular\b', 'Regular')
    ]
    
    for patron, tamano in patrones_tamano:
        if re.search(patron, texto_principal, flags=re.IGNORECASE):
            return tamano
            
    # 2. Si no viene el nombre, buscar las onzas en el texto y convertirlas a su talla Starbucks
    match_oz = re.search(r'\b(\d+(?:[.,]\d+)?)\s*(?:fl\.?\s*)?oz\b', texto_principal, flags=re.IGNORECASE)
    if match_oz:
        val_str = match_oz.group(1).replace(',', '.')
        tamano_mapeado = mapear_oz_a_tamano(val_str)
        if tamano_mapeado:
            return tamano_mapeado
        return f"{val_str} fl oz"
        
    # 3. Respaldo usando la columna Serving_Size
    serving_size = fila.get('Serving_Size')
    serving_unit = str(fila.get('Serving_Size_Unit', '')).strip().lower()
    if pd.notna(serving_size) and str(serving_size).strip() != '':
        tamano_mapeado = mapear_oz_a_tamano(serving_size)
        if tamano_mapeado:
            return tamano_mapeado
        return f"{serving_size} {serving_unit if serving_unit else 'fl oz'}"
        
    return 'Estándar'


def limpiar_nombre_bebida(nombre: str) -> str:
    """
    Extrae el nombre base puro de la bebida eliminando modificadores de leche,
    crema batida, tamaños residuales y conectores (&, Iced, etc.) al final.
    """
    if not isinstance(nombre, str):
        return 'Bebida sin nombre'
    
    limpio = nombre.strip()
    
    # 1. Separar todo lo que venga después de 'w/' o 'w/out' (ingredientes agregados)
    if re.search(r'\s+w/(?:out)?\s*', limpio, flags=re.IGNORECASE):
        limpio = re.split(r'\s+w/(?:out)?\s*', limpio, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        
    # 2. Separar si introduce modificadores con 'with' o 'without'
    if re.search(r'\s+(?:with|without)\s+(?:nonfat|2%|1%|whole|soy|almond|coconut|oat|milk|whip)', limpio, flags=re.IGNORECASE):
        limpio = re.split(r'\s+(?:with|without)\s+', limpio, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        
    # 3. Separar por la primera coma (donde van tamaños como ", Grande", ", Tall, 12 oz", ", 16 oz")
    if ',' in limpio:
        limpio = limpio.split(',')[0].strip()
        
    # 4. Eliminar tamaños si quedaron sueltos al final sin coma (ej. 'Venti Iced', 'Tall', 'Grande')
    patron_tamano_final = r'\b(?:Trenta|Venti(?:\s*Iced)?|Grande|Tall|Short|Doppio|Solo|Triple|Quad|Kids|Mini|\d+(?:\.\d+)?\s*(?:fl\.?\s*)?oz\.?)\b.*$'
    limpio = re.sub(patron_tamano_final, '', limpio, flags=re.IGNORECASE).strip()
    
    # 5. Limpiar conectores y puntuación residuales colgando al final (&, and, Iced, guiones, comas)
    limpio = re.sub(r'(\s*(&|\band\b|\bor\b|\bw/\b|\bwith\b|\bwithout\b|\bw/o\b|\biced\b|[,\-–/])\s*)+$', '', limpio, flags=re.IGNORECASE).strip()
    limpio = re.sub(r'\s{2,}', ' ', limpio).strip()
    
    return limpio if limpio else nombre.strip()


# ==========================================
# 3. PROCESAMIENTO PRINCIPAL DEL DATASET
# ==========================================

def procesar_dataset():
    # Lectura en UTF-8 (con fallback a utf-8-sig por si tiene BOM)
    df = pd.read_csv(INPUT_CSV, encoding='utf-8-sig', low_memory=False)
    
    # 1. Filtrar únicamente la categoría de bebidas ('Beverages')
    if 'Food_Category' in df.columns:
        df = df[df['Food_Category'].astype(str).str.strip().str.lower() == 'beverages'].copy()
    
    # 2. Ignorar (eliminar) la columna de año
    columnas_ano = [col for col in df.columns if col.lower() == 'year']
    df.drop(columns=columnas_ano, inplace=True, errors='ignore')
    
    # Texto combinado de nombre y descripción para extraer atributos con mayor precisión
    texto_combinado = (
        df.get('Item_Name', pd.Series('', index=df.index)).fillna('').astype(str) + ' ' +
        df.get('Item_Description', pd.Series('', index=df.index)).fillna('').astype(str)
    )
    
    # 3. Extraer tamaño de vaso, tipo de leche y booleano de crema
    df['Tamano_Vaso'] = df.apply(extraer_tamano_vaso, axis=1)
    df['Tipo_Leche'] = texto_combinado.apply(extraer_tipo_leche)
    df['Tiene_Crema'] = texto_combinado.apply(detectar_crema).astype(bool)
    
    # 4. Limpiar el nombre de la bebida para dejar solo el nombre base
    if 'Item_Name' in df.columns:
        df['Item_Name'] = df['Item_Name'].apply(limpiar_nombre_bebida)
    if 'Restaurant_Item_Name' in df.columns:
        df['Restaurant_Item_Name'] = df['Restaurant_Item_Name'].apply(limpiar_nombre_bebida)
        
    # ==========================================
    # 4. IMPUTACIÓN DE DATOS VACÍOS
    # ==========================================
    
    # A. Columnas binarias / indicadores (rellenar vacíos con 0)
    cols_binarias = ['Kids_Meal', 'Limited_Time_Offer', 'Regional', 'Shareable']
    for col in cols_binarias:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            
    # B. Columnas numéricas nutricionales y de porción
    cols_nutricionales_base = [
        'Serving_Size', 'Calories', 'Total_Fat', 'Saturated_Fat', 'Trans_Fat',
        'Cholesterol', 'Sodium', 'Potassium', 'Carbohydrates', 'Fiber', 'Sugar', 'Protein'
    ]
    cols_nutricionales_100g = [f"{col}_100g" for col in cols_nutricionales_base if col != 'Serving_Size']
    todas_numericas = [c for c in (cols_nutricionales_base + cols_nutricionales_100g) if c in df.columns]
    
    # Convertir a numérico
    for col in todas_numericas:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    # Imputar primero con la mediana de la misma bebida (mismo Item_Name) y luego mediana general o 0.0
    for col in todas_numericas:
        if df[col].isna().any():
            df[col] = df.groupby('Item_Name')[col].transform(lambda s: s.fillna(s.median()))
            mediana_global = df[col].median()
            valor_respaldo = round(float(mediana_global), 2) if pd.notna(mediana_global) else 0.0
            df[col] = df[col].fillna(valor_respaldo).round(2)
            
    # Si algún valor _100g sigue en 0 pero su valor base y Serving_Size son > 0, recalcular proporcionalmente
    if 'Serving_Size' in df.columns:
        for col in cols_nutricionales_base:
            col_100g = f"{col}_100g"
            if col != 'Serving_Size' and col in df.columns and col_100g in df.columns:
                mask = (df[col_100g] == 0) & (df[col] > 0) & (df['Serving_Size'] > 0)
                df.loc[mask, col_100g] = ((df.loc[mask, col] / df.loc[mask, 'Serving_Size']) * 100).round(2)

    # C. Columnas de texto y descriptivas
    if 'Item_Description' in df.columns:
        df['Item_Description'] = df['Item_Description'].replace('', np.nan).fillna(df['Item_Name'])
    if 'Serving_Size_Unit' in df.columns:
        df['Serving_Size_Unit'] = df['Serving_Size_Unit'].replace('', np.nan).fillna('fl oz')
    if 'Serving_Size_household' in df.columns:
        df['Serving_Size_household'] = df['Serving_Size_household'].replace('', np.nan).fillna(df['Tamano_Vaso'])
    if 'Serving_Size_text' in df.columns:
        df['Serving_Size_text'] = (
            df['Serving_Size_text']
            .replace('', np.nan)
            .fillna(df['Serving_Size'].astype(str) + ' ' + df['Serving_Size_Unit'].astype(str))
        )

    # D. Red de seguridad para cualquier otra columna restante en el dataset
    for col in df.columns:
        if df[col].isna().any():
            if pd.api.types.is_numeric_dtype(df[col]):
                df[col] = df[col].fillna(0)
            else:
                df[col] = df[col].fillna('No especificado')

    # Eliminar posibles duplicados exactos generados al ignorar el año
    df.drop_duplicates(inplace=True)

    # ==========================================
    # 5. EXPORTACIÓN A JSON EN UTF-8
    # ==========================================
    registros = df.to_dict(orient='records')
    with open(OUTPUT_JSON, mode='w', encoding='utf-8') as archivo_json:
        json.dump(registros, archivo_json, ensure_ascii=False, indent=2)
        
    print(f"Proceso completado: {len(registros)} bebidas exportadas en '{OUTPUT_JSON}'.")

if __name__ == '__main__':
    procesar_dataset()