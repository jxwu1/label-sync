from flask import jsonify

from schemas import ServiceResult


def json_result(result: ServiceResult):
    return jsonify(result.to_response_body()), result.status_code
