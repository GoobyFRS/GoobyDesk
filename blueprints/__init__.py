from .api_module import api_module_bp
from .reports_module import reports_module_bp
from .changes_module import changes_module_bp
from .itsm_module import itsm_module_bp
from .hr_module import hr_module_bp
from .crm_module import crm_module_bp
from .serviceid_module import serviceid_module_bp
from.media_request_module import media_request_module_bp

__all__ = ["reports_module_bp", "changes_module_bp", "itsm_module_bp", 
"hr_module_bp", "crm_module_bp", "serviceid_module_bp", "api_module_bp", "media_request_module_bp"]