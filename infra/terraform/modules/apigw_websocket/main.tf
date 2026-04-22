variable "name_prefix" { type = string }
variable "connect_lambda_arn" { type = string }
variable "disconnect_lambda_arn" { type = string }

resource "aws_apigatewayv2_api" "ws" {
  name                       = "${var.name_prefix}-ws-api"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
}

resource "aws_apigatewayv2_integration" "connect" {
  api_id           = aws_apigatewayv2_api.ws.id
  integration_type = "AWS_PROXY"
  integration_uri  = var.connect_lambda_arn
}

resource "aws_apigatewayv2_integration" "disconnect" {
  api_id           = aws_apigatewayv2_api.ws.id
  integration_type = "AWS_PROXY"
  integration_uri  = var.disconnect_lambda_arn
}

resource "aws_apigatewayv2_route" "connect" {
  api_id    = aws_apigatewayv2_api.ws.id
  route_key = "$connect"
  target    = "integrations/${aws_apigatewayv2_integration.connect.id}"
}

resource "aws_apigatewayv2_route" "disconnect" {
  api_id    = aws_apigatewayv2_api.ws.id
  route_key = "$disconnect"
  target    = "integrations/${aws_apigatewayv2_integration.disconnect.id}"
}

resource "aws_apigatewayv2_deployment" "ws" {
  api_id      = aws_apigatewayv2_api.ws.id
  description = "Streaming platform WebSocket"

  depends_on = [
    aws_apigatewayv2_route.connect,
    aws_apigatewayv2_route.disconnect,
  ]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_apigatewayv2_stage" "prod" {
  api_id        = aws_apigatewayv2_api.ws.id
  deployment_id = aws_apigatewayv2_deployment.ws.id
  name          = "prod"
  auto_deploy   = true
}

resource "aws_lambda_permission" "connect" {
  statement_id  = "AllowAPIGatewayConnect"
  action        = "lambda:InvokeFunction"
  function_name = var.connect_lambda_arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ws.execution_arn}/*/*"
}

resource "aws_lambda_permission" "disconnect" {
  statement_id  = "AllowAPIGatewayDisconnect"
  action        = "lambda:InvokeFunction"
  function_name = var.disconnect_lambda_arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ws.execution_arn}/*/*"
}

output "websocket_url" { value = aws_apigatewayv2_api.ws.api_endpoint }
output "ws_management_endpoint" {
  value = "https://${aws_apigatewayv2_api.ws.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${aws_apigatewayv2_stage.prod.name}"
}

data "aws_region" "current" {}
