export type Data = Record<string, any>;
export type Run = {id:string;ticker:string;risk:string;source:string;status:string;created:number;result?:Data;error?:string};
export type RunEvent = {id:number;type:string;created:number;payload:Data};
