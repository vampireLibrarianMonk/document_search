FROM node:20-alpine AS build
WORKDIR /app

ARG IMAGE_TAG=latest
ARG BUILD_DATE=unknown
ARG GIT_HASH=unknown

COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine

ARG IMAGE_TAG=latest
ARG BUILD_DATE=unknown
ARG GIT_HASH=unknown

LABEL org.opencontainers.image.version="${IMAGE_TAG}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${GIT_HASH}"

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
