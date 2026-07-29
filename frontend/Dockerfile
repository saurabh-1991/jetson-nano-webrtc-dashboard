# Multi-stage build for production
FROM node:20-alpine as build

WORKDIR /app

COPY package*.json ./
RUN npm config set fetch-retries 6 \
	&& npm config set fetch-retry-factor 2 \
	&& npm config set fetch-retry-mintimeout 20000 \
	&& npm config set fetch-retry-maxtimeout 120000 \
	&& npm config set fetch-timeout 300000 \
	&& npm config set audit false \
	&& success=0 \
	&& for i in 1 2 3; do \
		 if npm ci --prefer-offline --no-audit; then success=1; break; fi; \
		 echo "npm ci retry $i failed"; \
		 sleep $((i * 12)); \
	   done \
	&& [ "$success" -eq 1 ]

COPY . .
RUN npm run build

# Nginx stage
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
