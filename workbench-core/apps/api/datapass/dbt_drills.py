"""Untrusted teaching SQL: literal fixture refs only, no Jinja execution."""
import ast
from .catalog import validate_sql

def compile_fixture_sql(source: str) -> str:
    if len(source)>40000:
        raise ValueError('dbt drill source limit is 40 KB.')
    out=[];i=0
    while i<len(source):
        # SQL literals/comments are not Jinja programs. Keep their bytes intact.
        if source[i] in "'\"":
            quote=source[i];j=i+1
            while j<len(source):
                if source[j]==quote:
                    if j+1<len(source) and source[j+1]==quote:j+=2;continue
                    j+=1;break
                j+=1
            out.append(source[i:j]);i=j;continue
        if source.startswith('--',i):
            j=source.find('\n',i);j=len(source) if j<0 else j
            out.append(source[i:j]);i=j;continue
        if source.startswith('/*',i):
            j=source.find('*/',i+2)
            if j<0:raise ValueError('Unclosed SQL comment.')
            out.append(source[i:j+2]);i=j+2;continue
        if source.startswith(('{{','{%','{#'),i):
            if not source.startswith('{{',i):raise ValueError('Jinja blocks, comments and macros are not supported in dbt drills.')
            end=source.find('}}',i+2)
            if end<0:raise ValueError('Unclosed literal dbt reference.')
            try:
                expr=ast.parse(source[i+2:end].strip(),mode='eval').body
            except (SyntaxError,RecursionError) as error:
                raise ValueError('Use only literal ref("input") or source("fixture", "input").') from error
            if not isinstance(expr,ast.Call) or not isinstance(expr.func,ast.Name) or expr.keywords or any(not isinstance(a,ast.Constant) or not isinstance(a.value,str) for a in expr.args):
                raise ValueError('Dynamic Jinja and Python expressions are unavailable in dbt drills.')
            args=[a.value for a in expr.args]
            if not ((expr.func.id=='ref' and args==['input']) or (expr.func.id=='source' and args==['fixture','input'])):
                raise ValueError('This drill binds only the versioned input fixture; unknown ref/source.')
            out.append('input');i=end+2;continue
        out.append(source[i]);i+=1
    result=''.join(out)
    validate_sql(result,read_only=True)
    return result
